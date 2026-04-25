"""Unix socket server for IPC between daemon and CLI."""

import json
import logging
import os
import socket
import threading
from typing import Callable

logger = logging.getLogger(__name__)

SOCKET_PATH = "/run/agent-linux/agent.sock"
SOCKET_DIR = os.path.dirname(SOCKET_PATH)


class SocketServer:
    def __init__(self, message_handler: Callable[[dict], dict]):
        self._handler = message_handler
        self._server: socket.socket | None = None
        self._running = False

    def start(self) -> None:
        os.makedirs(SOCKET_DIR, mode=0o755, exist_ok=True)
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)

        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(SOCKET_PATH)
        os.chmod(SOCKET_PATH, 0o660)

        try:
            import grp
            gid = grp.getgrnam("agent-linux").gr_gid
            os.chown(SOCKET_PATH, -1, gid)
        except (KeyError, PermissionError):
            pass

        self._server.listen(5)
        self._running = True
        logger.info("Socket server listening on %s", SOCKET_PATH)

        while self._running:
            try:
                self._server.settimeout(1.0)
                try:
                    conn, _ = self._server.accept()
                except socket.timeout:
                    continue
                thread = threading.Thread(target=self._handle_connection, args=(conn,), daemon=True)
                thread.start()
            except Exception as e:
                if self._running:
                    logger.error("Socket accept error: %s", e)

    def stop(self) -> None:
        self._running = False
        if self._server:
            self._server.close()
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)

    def _handle_connection(self, conn: socket.socket) -> None:
        try:
            data = _recv_all(conn)
            if not data:
                return
            request = json.loads(data)
            response = self._handler(request)
            conn.sendall(json.dumps(response).encode() + b"\n")
        except Exception as e:
            logger.error("Connection handler error: %s", e)
            try:
                conn.sendall(json.dumps({"error": str(e)}).encode() + b"\n")
            except Exception:
                pass
        finally:
            conn.close()


def _recv_all(conn: socket.socket, bufsize: int = 65536) -> bytes:
    chunks = []
    while True:
        chunk = conn.recv(bufsize)
        if not chunk:
            break
        chunks.append(chunk)
        if chunk.endswith(b"\n"):
            break
    return b"".join(chunks).strip()


def send_request(payload: dict, socket_path: str = SOCKET_PATH, timeout: int = 300) -> dict:
    """Send a request to the daemon and return its response."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect(socket_path)
    sock.sendall(json.dumps(payload).encode() + b"\n")
    data = _recv_all(sock)
    sock.close()
    return json.loads(data)
