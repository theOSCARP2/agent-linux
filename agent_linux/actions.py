"""Secure command execution with allowlist enforcement."""

import subprocess
import logging
import time
import os
import shlex
from typing import Optional

logger = logging.getLogger(__name__)

LOG_PATH = "/var/log/agent-linux/actions.log"


def _log_action(command: str, result: str, user: str = "agent-linux") -> None:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    entry = f"[{timestamp}] user={user} cmd={command!r} result={result!r}\n"
    with open(LOG_PATH, "a") as f:
        f.write(entry)


def execute_command(
    command: str,
    allowed_commands: list[str],
    timeout: int = 30,
    user: str = "agent-linux",
) -> dict:
    """Execute a shell command if its base program is in the allowlist."""
    try:
        args = shlex.split(command)
    except ValueError as e:
        return {"success": False, "stdout": "", "stderr": str(e), "returncode": -1}

    if not args:
        return {"success": False, "stdout": "", "stderr": "Empty command", "returncode": -1}

    base = os.path.basename(args[0])
    if base not in allowed_commands:
        msg = f"Command '{base}' is not in the allowed list"
        _log_action(command, f"BLOCKED: {msg}", user)
        return {"success": False, "stdout": "", "stderr": msg, "returncode": -1}

    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        result_summary = f"rc={proc.returncode}"
        _log_action(command, result_summary, user)
        return {
            "success": proc.returncode == 0,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "returncode": proc.returncode,
        }
    except subprocess.TimeoutExpired:
        msg = f"Command timed out after {timeout}s"
        _log_action(command, f"TIMEOUT: {msg}", user)
        return {"success": False, "stdout": "", "stderr": msg, "returncode": -1}
    except Exception as e:
        _log_action(command, f"ERROR: {e}", user)
        return {"success": False, "stdout": "", "stderr": str(e), "returncode": -1}


def read_file(path: str, max_bytes: int = 65536) -> dict:
    """Read a file from the filesystem (safety-limited to max_bytes)."""
    try:
        with open(path, "r", errors="replace") as f:
            content = f.read(max_bytes)
        return {"success": True, "content": content}
    except Exception as e:
        return {"success": False, "content": "", "error": str(e)}


def get_service_status(service: str, allowed_commands: list[str]) -> dict:
    """Return systemd service status."""
    return execute_command(f"systemctl status {service}", allowed_commands)


def get_docker_status(allowed_commands: list[str]) -> dict:
    """Return docker ps output."""
    return execute_command(
        "docker ps --format '{{.Names}}\\t{{.Status}}\\t{{.Image}}'",
        allowed_commands,
    )


def get_network_rules(allowed_commands: list[str]) -> dict:
    """Return current nftables rules (falls back to iptables)."""
    result = execute_command("nft list ruleset", allowed_commands)
    if not result["success"]:
        result = execute_command("iptables -L -n -v", allowed_commands)
    return result


def get_system_metrics() -> dict:
    """Return real-time CPU, RAM, disk metrics via psutil."""
    try:
        import psutil
        return {
            "success": True,
            "cpu_percent": psutil.cpu_percent(interval=1),
            "ram": dict(psutil.virtual_memory()._asdict()),
            "disk": {
                part.mountpoint: dict(psutil.disk_usage(part.mountpoint)._asdict())
                for part in psutil.disk_partitions(all=False)
                if part.fstype
            },
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
