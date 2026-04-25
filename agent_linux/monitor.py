"""System monitoring loop — collects metrics and detects anomalies."""

import hashlib
import logging
import subprocess
import time
from collections import deque
from typing import Optional

import psutil

logger = logging.getLogger(__name__)

# Rolling buffer of monitoring snapshots
_event_buffer: deque = deque(maxlen=500)


def get_events() -> list:
    return list(_event_buffer)


def get_recent_events(n: int = 20) -> list:
    return list(_event_buffer)[-n:]


def collect_snapshot(config: dict) -> dict:
    """Collect a full system snapshot and return it."""
    snapshot = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "cpu": _cpu_metrics(),
        "ram": _ram_metrics(),
        "disk": _disk_metrics(),
        "docker": _docker_metrics(),
        "network": _network_metrics(),
        "auth_log": _auth_log_tail(),
        "firewall_hash": _firewall_hash(),
        "failed_services": _failed_services(),
    }
    _event_buffer.append(snapshot)
    return snapshot


def check_alerts(snapshot: dict, config: dict) -> list[str]:
    """Return a list of alert strings for any thresholds exceeded."""
    alerts = []
    mon = config.get("monitor", {})
    thr = config.get("thresholds", {})

    if snapshot["cpu"].get("percent", 0) >= mon.get("cpu_threshold", 85):
        alerts.append(f"CPU usage {snapshot['cpu']['percent']}% >= {mon['cpu_threshold']}%")

    ram_pct = snapshot["ram"].get("percent", 0)
    if ram_pct >= mon.get("ram_threshold", 90):
        alerts.append(f"RAM usage {ram_pct}% >= {mon['ram_threshold']}%")

    for mount, usage in snapshot["disk"].items():
        if usage.get("percent", 0) >= mon.get("disk_threshold", 85):
            alerts.append(f"Disk {mount} at {usage['percent']}% >= {mon['disk_threshold']}%")

    restart_limit = thr.get("docker_restart_alert", 5)
    for container in snapshot["docker"]:
        restarts = container.get("restarts", 0)
        if restarts >= restart_limit:
            alerts.append(f"Docker {container['name']} has {restarts} restarts")

    for svc in snapshot["failed_services"]:
        alerts.append(f"systemd service failed: {svc}")

    return alerts


# ── collectors ────────────────────────────────────────────────────────────────

def _cpu_metrics() -> dict:
    return {"percent": psutil.cpu_percent(interval=1), "count": psutil.cpu_count()}


def _ram_metrics() -> dict:
    m = psutil.virtual_memory()
    return {"total": m.total, "available": m.available, "percent": m.percent}


def _disk_metrics() -> dict:
    result = {}
    for part in psutil.disk_partitions(all=False):
        if not part.fstype:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
            result[part.mountpoint] = {
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "percent": usage.percent,
            }
        except PermissionError:
            pass
    return result


def _docker_metrics() -> list:
    try:
        import docker as docker_sdk
        client = docker_sdk.from_env()
        containers = []
        for c in client.containers.list(all=True):
            stats = {}
            try:
                raw = c.stats(stream=False)
                cpu_delta = (
                    raw["cpu_stats"]["cpu_usage"]["total_usage"]
                    - raw["precpu_stats"]["cpu_usage"]["total_usage"]
                )
                sys_delta = (
                    raw["cpu_stats"].get("system_cpu_usage", 0)
                    - raw["precpu_stats"].get("system_cpu_usage", 0)
                )
                cpu_pct = (cpu_delta / sys_delta * 100) if sys_delta > 0 else 0
                mem = raw["memory_stats"]
                stats = {
                    "cpu_percent": round(cpu_pct, 2),
                    "mem_usage": mem.get("usage", 0),
                    "mem_limit": mem.get("limit", 0),
                }
            except Exception:
                pass
            containers.append({
                "name": c.name,
                "status": c.status,
                "image": c.image.tags[0] if c.image.tags else c.image.short_id,
                "restarts": c.attrs.get("RestartCount", 0),
                **stats,
            })
        return containers
    except Exception as e:
        logger.debug("Docker metrics unavailable: %s", e)
        return []


def _network_metrics() -> dict:
    connections = []
    for conn in psutil.net_connections(kind="inet"):
        if conn.status in ("ESTABLISHED", "LISTEN"):
            connections.append({
                "laddr": f"{conn.laddr.ip}:{conn.laddr.port}" if conn.laddr else "",
                "raddr": f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else "",
                "status": conn.status,
                "pid": conn.pid,
            })
    return {"connections": connections[:100]}  # cap at 100


def _auth_log_tail(lines: int = 20) -> list[str]:
    for path in ("/var/log/auth.log", "/var/log/secure"):
        try:
            result = subprocess.run(
                ["tail", "-n", str(lines), path],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.splitlines()
        except Exception:
            pass
    return []


def _firewall_hash() -> str:
    """Return a short hash of current firewall rules to detect changes."""
    for cmd in (["nft", "list", "ruleset"], ["iptables-save"]):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return hashlib.sha256(result.stdout.encode()).hexdigest()[:16]
        except Exception:
            pass
    return ""


def _failed_services() -> list[str]:
    try:
        result = subprocess.run(
            ["systemctl", "list-units", "--state=failed", "--no-legend", "--plain"],
            capture_output=True, text=True, timeout=5,
        )
        failed = []
        for line in result.stdout.splitlines():
            parts = line.split()
            if parts:
                failed.append(parts[0])
        return failed
    except Exception:
        return []
