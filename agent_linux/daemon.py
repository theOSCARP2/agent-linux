"""Daemon process: monitoring loop + socket server."""

import json
import logging
import os
import signal
import sys
import threading
import time

from .config import load_config
from .claude_client import ClaudeClient
from . import monitor
from .socket_server import SocketServer

LOG_PATH = "/var/log/agent-linux/actions.log"
PID_FILE = "/run/agent-linux/agent.pid"


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

    # Write PID file
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

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
            snapshot = monitor.get_recent_events(1)
            return {
                "type": "status",
                "snapshot": snapshot[-1] if snapshot else {},
                "alerts": monitor.check_alerts(snapshot[-1], config) if snapshot else [],
            }

        if kind == "events":
            n = request.get("n", 20)
            return {"type": "events", "events": monitor.get_recent_events(n)}

        return {"type": "error", "message": f"Unknown request type: {kind}"}

    server = SocketServer(handle_socket_message)
    server_thread = threading.Thread(target=server.start, daemon=True)
    server_thread.start()
    logger.info("Socket server started")

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
