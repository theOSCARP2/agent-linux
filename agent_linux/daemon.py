"""Daemon process: monitoring loop + socket server."""

import logging
import os
import signal
import sys
import threading
import time

from . import __version__
from .config import load_config
from .claude_client import ClaudeClient
from . import monitor
from .socket_server import SocketServer
from .updater import check_for_update

LOG_PATH = "/var/log/agent-linux/actions.log"
PID_FILE = "/run/agent-linux/agent.pid"
VERSION_CHECK_INTERVAL = 86400  # 24 hours


def setup_logging() -> None:
    os.makedirs("/var/log/agent-linux", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH),
            logging.StreamHandler(sys.stdout),
        ],
    )


def main() -> None:
    setup_logging()
    logger = logging.getLogger("daemon")
    config = load_config()

    if not config.get("anthropic_api_key"):
        logger.error("anthropic_api_key not set in config — exiting")
        sys.exit(1)

    client = ClaudeClient(config)

    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    # Shared mutable state (written by monitor loop, read by socket handler)
    state = {
        "update_available": None,   # str version or None
        "last_version_check": 0.0,
    }

    def handle_socket_message(request: dict) -> dict:
        kind = request.get("type")

        if kind == "chat":
            try:
                reply = client.chat(request["message"])
                return {"type": "reply", "message": reply}
            except Exception as e:
                logger.error("Chat error: %s", e)
                return {"type": "error", "message": str(e)}

        if kind == "status":
            recent = monitor.get_recent_events(1)
            snapshot = recent[-1] if recent else {}
            return {
                "type": "status",
                "snapshot": snapshot,
                "alerts": monitor.check_alerts(snapshot, config) if snapshot else [],
                "current_version": __version__,
                "update_available": state["update_available"],
            }

        if kind == "events":
            return {"type": "events", "events": monitor.get_recent_events(request.get("n", 20))}

        return {"type": "error", "message": f"Unknown request type: {kind}"}

    server = SocketServer(handle_socket_message)
    server_thread = threading.Thread(target=server.start, daemon=True)
    server_thread.start()
    logger.info("Socket server started (agent-linux v%s)", __version__)

    def _shutdown(sig, frame):
        logger.info("Received signal %s, shutting down", sig)
        server.stop()
        if os.path.exists(PID_FILE):
            os.unlink(PID_FILE)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    interval = config.get("monitor", {}).get("interval", 60)
    logger.info("Monitor loop starting (interval=%ss)", interval)

    while True:
        now = time.time()

        # Version check every 24h
        if now - state["last_version_check"] >= VERSION_CHECK_INTERVAL:
            try:
                latest = check_for_update(__version__)
                state["update_available"] = latest
                if latest:
                    logger.info(
                        "Update available: v%s → v%s — run: sudo agent-linux update",
                        __version__, latest,
                    )
            except Exception as e:
                logger.debug("Version check failed: %s", e)
            state["last_version_check"] = now

        # Monitoring snapshot + alert
        try:
            snapshot = monitor.collect_snapshot(config)
            alerts = monitor.check_alerts(snapshot, config)
            if alerts:
                alert_msg = "; ".join(alerts)
                logger.warning("ALERT: %s", alert_msg)
                try:
                    reply = client.alert(alert_msg)
                    logger.info("Claude response to alert: %s", reply[:200])
                except Exception as e:
                    logger.error("Failed to send alert to Claude: %s", e)
        except Exception as e:
            logger.error("Monitor loop error: %s", e)

        time.sleep(interval)


if __name__ == "__main__":
    main()
