#!/usr/bin/env python3
"""agent-linux CLI — single entry point for install, manage and chat."""

import getpass
import grp
import json
import os
import pwd
import readline
import shutil
import stat
import subprocess
import sys
import textwrap
import time

# ── Rich is optional during bootstrap (install downloads it) ─────────────────
try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.text import Text
    _RICH = True
except ImportError:
    _RICH = False

# ── Constants ─────────────────────────────────────────────────────────────────

VERSION = "1.0.0"

VENV_DIR = "/opt/agent-linux/venv"

# Make agent_linux package importable from the venv
_venv_site = os.path.join(
    VENV_DIR, "lib",
    f"python{sys.version_info.major}.{sys.version_info.minor}",
    "site-packages",
)
if _venv_site not in sys.path:
    sys.path.insert(0, _venv_site)

SOCKET_PATH = "/run/agent-linux/agent.sock"
CONFIG_DIR = "/etc/agent-linux"
CONFIG_PATH = f"{CONFIG_DIR}/config.yml"
LOG_DIR = "/var/log/agent-linux"
SERVICE_NAME = "agent-linux"
SYSTEM_USER = "agent-linux"
INSTALL_DIR = "/opt/agent-linux"
BIN_PATH = "/usr/local/bin/agent-linux"
SYSTEMD_SERVICE_SRC = os.path.join(os.path.dirname(__file__), "..", "systemd", "agent-linux.service")
SUDOERS_SRC = os.path.join(os.path.dirname(__file__), "..", "sudoers.d", "agent-linux")

console = Console() if _RICH else None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _print(msg: str, style: str = "") -> None:
    if _RICH and console:
        console.print(msg, style=style)
    else:
        print(msg)


def _info(msg: str) -> None:
    _print(f"[cyan]→[/cyan] {msg}" if _RICH else f"→ {msg}")


def _ok(msg: str) -> None:
    _print(f"[green]✓[/green] {msg}" if _RICH else f"✓ {msg}")


def _warn(msg: str) -> None:
    _print(f"[yellow]![/yellow] {msg}" if _RICH else f"! {msg}")


def _err(msg: str) -> None:
    _print(f"[red]✗[/red] {msg}" if _RICH else f"✗ {msg}")


def _run(cmd: list[str], check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    kwargs = {"capture_output": capture, "text": True}
    result = subprocess.run(cmd, **kwargs)
    if check and result.returncode != 0:
        stderr = result.stderr if capture else ""
        raise RuntimeError(f"Command {cmd} failed (rc={result.returncode}): {stderr}")
    return result


def _require_root() -> None:
    if os.geteuid() != 0:
        _err("This command must be run as root (use sudo).")
        sys.exit(1)


# ── Sub-commands ──────────────────────────────────────────────────────────────

def cmd_install() -> None:
    _require_root()
    _print("\n[bold]agent-linux installer[/bold]\n" if _RICH else "\nagent-linux installer\n")

    # 1. Python version check
    if sys.version_info < (3, 10):
        _err("Python 3.10+ required")
        sys.exit(1)
    _ok(f"Python {sys.version.split()[0]}")

    # 2. Create virtualenv at INSTALL_DIR to isolate from system packages
    venv_dir = os.path.join(INSTALL_DIR, "venv")
    venv_python = os.path.join(venv_dir, "bin", "python3")
    venv_pip = os.path.join(venv_dir, "bin", "pip")
    venv_ok = os.path.exists(venv_python) and os.path.exists(venv_pip)
    if not venv_ok:
        # Remove broken venv if it exists
        if os.path.exists(venv_dir):
            shutil.rmtree(venv_dir)
        _info("Installing python3-venv…")
        _run(["apt-get", "install", "-y", "-q", "python3-venv"])
        _info(f"Creating virtualenv at {venv_dir}…")
        _run([sys.executable, "-m", "venv", venv_dir])
        # Bootstrap pip inside the venv
        _run([venv_python, "-m", "ensurepip", "--upgrade"])
        _run([venv_python, "-m", "pip", "install", "-q", "--upgrade", "pip"])
        _ok("Virtualenv created")

    # 3. pip packages inside the venv
    _info("Installing Python dependencies…")
    _run([venv_python, "-m", "pip", "install", "-q",
          "anthropic", "psutil", "docker", "rich", "pyyaml"])
    _ok("Dependencies installed")

    # 3. Create system user
    try:
        pwd.getpwnam(SYSTEM_USER)
        _ok(f"User '{SYSTEM_USER}' already exists")
    except KeyError:
        _info(f"Creating system user '{SYSTEM_USER}'…")
        _run(["useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin",
              "--groups", "docker", SYSTEM_USER], check=False)
        _run(["useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin",
              SYSTEM_USER], check=False)
        _ok(f"User '{SYSTEM_USER}' created")

    # 4. Create group if missing
    try:
        grp.getgrnam(SYSTEM_USER)
    except KeyError:
        _run(["groupadd", SYSTEM_USER], check=False)

    # 5. Directories
    for d in [CONFIG_DIR, LOG_DIR, "/run/agent-linux", INSTALL_DIR]:
        os.makedirs(d, exist_ok=True)
    _run(["chown", "-R", f"{SYSTEM_USER}:{SYSTEM_USER}", LOG_DIR, "/run/agent-linux"])
    _ok("Directories created")

    # 6. Install package into the venv
    # Install from GitHub — the CLI runs as a standalone script so no local source is available
    _info("Installing agent-linux package…")
    pkg_url = "https://github.com/theOSCARP2/agent-linux/archive/refs/heads/master.tar.gz"
    _run([venv_python, "-m", "pip", "install", "-q", pkg_url])
    _ok("Package installed")

    # 7. Install CLI symlink
    self_path = os.path.abspath(__file__)
    if not os.path.exists(BIN_PATH):
        os.symlink(self_path, BIN_PATH)
    os.chmod(self_path, 0o755)
    _ok(f"CLI available at {BIN_PATH}")

    # 8. Sudoers
    sudoers_dst = "/etc/sudoers.d/agent-linux"
    if os.path.exists(SUDOERS_SRC):
        shutil.copy2(SUDOERS_SRC, sudoers_dst)
        os.chmod(sudoers_dst, 0o440)
        _ok("Sudoers rules installed")

    # 9. Systemd service
    service_dst = f"/etc/systemd/system/{SERVICE_NAME}.service"
    if os.path.exists(SYSTEMD_SERVICE_SRC):
        shutil.copy2(SYSTEMD_SERVICE_SRC, service_dst)
        _run(["systemctl", "daemon-reload"])
        _ok("Systemd service installed")
    else:
        _warn("systemd service file not found — writing default")
        _write_default_service(service_dst)
        _run(["systemctl", "daemon-reload"])

    # 10. API key
    api_key = ""
    while not api_key.strip():
        api_key = getpass.getpass("\nAnthropic API key (sk-ant-…): ").strip()

    config_content = f"""anthropic_api_key: "{api_key}"

monitor:
  interval: 60
  cpu_threshold: 85
  ram_threshold: 90
  disk_threshold: 85

thresholds:
  docker_restart_alert: 5

allowed_commands:
  - iptables
  - nft
  - systemctl
  - useradd
  - userdel
  - passwd
  - docker
  - journalctl
  - ss
  - ip
"""
    with open(CONFIG_PATH, "w") as f:
        f.write(config_content)
    os.chmod(CONFIG_PATH, 0o600)
    _run(["chown", f"{SYSTEM_USER}:{SYSTEM_USER}", CONFIG_PATH])
    _ok(f"Config written to {CONFIG_PATH}")

    # 11. Start service
    _run(["systemctl", "enable", "--now", SERVICE_NAME])
    time.sleep(2)
    result = _run(["systemctl", "is-active", SERVICE_NAME], check=False, capture=True)
    if result.stdout.strip() == "active":
        _ok("Service is running")
    else:
        _warn("Service may not have started — check: journalctl -u agent-linux")

    _print(
        "\n[bold green]Installation complete![/bold green]\n"
        "Run [bold]agent-linux[/bold] to start chatting with your server.\n"
        if _RICH else
        "\nInstallation complete! Run 'agent-linux' to start chatting.\n"
    )


def _write_default_service(dst: str) -> None:
    content = textwrap.dedent(f"""\
        [Unit]
        Description=agent-linux AI server administration daemon
        After=network.target

        [Service]
        Type=simple
        User={SYSTEM_USER}
        Group={SYSTEM_USER}
        ExecStart={INSTALL_DIR}/venv/bin/python3 -m agent_linux.daemon
        Restart=on-failure
        RestartSec=5
        RuntimeDirectory=agent-linux
        RuntimeDirectoryMode=0755

        [Install]
        WantedBy=multi-user.target
    """)
    with open(dst, "w") as f:
        f.write(content)


def cmd_remove() -> None:
    _require_root()
    _info("Stopping and disabling service…")
    _run(["systemctl", "stop", SERVICE_NAME], check=False)
    _run(["systemctl", "disable", SERVICE_NAME], check=False)

    service_file = f"/etc/systemd/system/{SERVICE_NAME}.service"
    if os.path.exists(service_file):
        os.unlink(service_file)
    _run(["systemctl", "daemon-reload"])
    _ok("Service removed")

    for path in ["/etc/sudoers.d/agent-linux", CONFIG_PATH]:
        if os.path.exists(path):
            os.unlink(path)

    _run(["userdel", SYSTEM_USER], check=False)
    _ok("System user removed")

    for d in [CONFIG_DIR, LOG_DIR, "/run/agent-linux", INSTALL_DIR]:
        if os.path.exists(d):
            shutil.rmtree(d, ignore_errors=True)
    _ok("Directories removed")

    if os.path.exists(BIN_PATH) and os.path.islink(BIN_PATH):
        os.unlink(BIN_PATH)

    _ok("agent-linux removed")


def cmd_update() -> None:
    _require_root()
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from agent_linux.updater import check_for_update, perform_update

    _info(f"Current version: {VERSION}")
    _info("Checking for updates…")

    latest = check_for_update(VERSION)
    if not latest:
        _ok(f"Already up to date (v{VERSION}).")
        return

    _print(
        f"[bold yellow]New version available: v{latest}[/bold yellow]" if _RICH
        else f"New version available: v{latest}"
    )
    confirm = input(f"Update v{VERSION} → v{latest}? (o/n) ").strip().lower()
    if confirm not in ("o", "y", "oui", "yes"):
        _info("Update cancelled.")
        return

    _info("Installing update…")
    result = perform_update(VERSION)

    if not result["success"]:
        _err(result["message"])
        sys.exit(1)

    _ok(result["message"])
    _info("Restarting service…")
    _run(["systemctl", "restart", SERVICE_NAME], check=False)
    _ok("Service restarted.")


def cmd_service(action: str) -> None:
    _require_root()
    _run(["systemctl", action, SERVICE_NAME])
    _ok(f"Service {action}ed")


def cmd_status() -> None:
    _run(["systemctl", "status", SERVICE_NAME], check=False)


# ── Interactive chat ───────────────────────────────────────────────────────────

def cmd_chat() -> None:
    # Check daemon is reachable
    if not os.path.exists(SOCKET_PATH):
        _err(f"Daemon socket not found at {SOCKET_PATH}.")
        _err("Is the service running? Try: sudo agent-linux start")
        sys.exit(1)

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from agent_linux.socket_server import send_request

    # Banner
    try:
        resp = send_request({"type": "status"})
        snapshot = resp.get("snapshot", {})
        alerts = resp.get("alerts", [])
        _print_banner(
            snapshot, alerts,
            current_version=resp.get("current_version", ""),
            update_available=resp.get("update_available") or "",
        )
    except Exception as e:
        _warn(f"Could not fetch status: {e}")

    # readline history
    histfile = os.path.expanduser("~/.agent_linux_history")
    try:
        readline.read_history_file(histfile)
    except FileNotFoundError:
        pass
    readline.set_history_length(500)

    _print("[dim]Type 'exit' or press Ctrl+C to quit.[/dim]\n" if _RICH else "Type 'exit' or Ctrl+C to quit.\n")

    while True:
        try:
            user_input = input("vous > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "q"):
            break

        try:
            resp = send_request({"type": "chat", "message": user_input})
        except Exception as e:
            _err(f"Daemon unreachable: {e}")
            continue

        if resp.get("type") == "error":
            _err(resp.get("message", "Unknown error"))
            continue

        reply = resp.get("message", "")
        _print_reply(reply)

    try:
        readline.write_history_file(histfile)
    except Exception:
        pass


def _print_banner(snapshot: dict, alerts: list, current_version: str = "", update_available: str = "") -> None:
    cpu = snapshot.get("cpu", {}).get("percent", "?")
    ram = snapshot.get("ram", {}).get("percent", "?")
    failed = snapshot.get("failed_services", [])
    docker = snapshot.get("docker", [])
    up = sum(1 for c in docker if c.get("status") == "running")

    ver_str = f"v{current_version}" if current_version else f"v{VERSION}"
    lines = [
        f"agent-linux {ver_str}   CPU: {cpu}%   RAM: {ram}%   Docker: {up} up",
    ]
    if update_available:
        lines.append(f"↑ Update available: v{update_available} — run: sudo agent-linux update")
    if alerts:
        lines.append("⚠  " + " | ".join(alerts))
    if failed:
        lines.append("✗ Failed services: " + ", ".join(failed))

    if _RICH and console:
        alert_style = "bold red" if alerts else "bold green"
        panel = Panel("\n".join(lines), title="[bold]agent-linux[/bold]", style=alert_style)
        console.print(panel)
    else:
        print("=" * 60)
        for l in lines:
            print(l)
        print("=" * 60)


def _print_reply(reply: str) -> None:
    if _RICH and console:
        console.print(Markdown(reply), style="cyan")
    else:
        print(f"\nagent > {reply}\n")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]

    if not args:
        cmd_chat()
        return

    cmd = args[0].lower()

    if cmd in ("-v", "--version", "version"):
        print(f"agent-linux {VERSION}")
    elif cmd == "update":
        cmd_update()
    elif cmd == "install":
        cmd_install()
    elif cmd == "remove":
        cmd_remove()
    elif cmd in ("start", "stop", "restart"):
        cmd_service(cmd)
    elif cmd == "status":
        cmd_status()
    else:
        _err(f"Unknown command: {cmd}")
        print(f"agent-linux {VERSION}")
        print("Usage: agent-linux [install|remove|update|start|stop|restart|status|--version]")
        sys.exit(1)


if __name__ == "__main__":
    main()
