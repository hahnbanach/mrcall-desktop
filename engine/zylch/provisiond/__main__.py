"""Process entrypoint: `python -m zylch.provisiond`.

Builds the `AF_UNIX` HTTP server and serves forever. All configuration
(profiles root, Firebase project id, socket path) is resolved at CALL
time by `handler.config_*` — nothing here is an import-time constant, so
a systemd `EnvironmentFile=` change takes effect on the next process
start without touching this module.
"""

from __future__ import annotations

import logging
import os
import socket
import socketserver
from http.server import HTTPServer

from . import handler

logger = logging.getLogger(__name__)


class _UnixHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    """`HTTPServer` bound to an `AF_UNIX` path instead of a TCP host:port.

    One thread per connection (`daemon_threads`) so a slow or hostile
    client on one connection cannot stall the others — the same
    robustness goal `server_ws.py` gets for free from `websockets`'
    asyncio model.
    """

    address_family = socket.AF_UNIX
    daemon_threads = True

    def server_bind(self) -> None:
        # HTTPServer.server_bind() does `host, port = self.server_address[:2]`
        # to derive server_name/server_port — that assumes a (host, port)
        # tuple. An AF_UNIX server_address is a plain path string, so skip
        # straight to the socketserver-level bind and stub the rest.
        socketserver.TCPServer.server_bind(self)
        self.server_name = "localhost"
        self.server_port = 0


def _configure_logging() -> None:
    """stderr only — journald captures it (`journalctl -u zylch-provisiond`).

    No separate log file: unlike the per-profile `zylch-server@<uid>`
    daemons, provisiond is not bound to any one profile, so there is no
    profile dir to write a `zylch.log` into. Mirrors the format
    `cli.main._configure_logging` uses elsewhere in the engine.
    """
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> None:
    _configure_logging()
    socket_path = handler.config_socket_path()

    socket_dir = os.path.dirname(socket_path)
    if socket_dir:
        os.makedirs(socket_dir, exist_ok=True)

    # Remove a stale socket left by a SIGKILLed predecessor: stdlib socket
    # binding does not pre-unlink, so a leftover file makes bind() fail
    # with EADDRINUSE and the daemon can't respawn. Mirrors server_ws.py's
    # serve_ws() unix-socket lifecycle.
    if os.path.exists(socket_path):
        logger.info(f"[provisiond] removing stale socket {socket_path}")
        os.unlink(socket_path)

    server = _UnixHTTPServer(socket_path, handler.ProvisiondRequestHandler)
    # Group-writable so the Caddy reverse-proxy (group `caddy`, inherited
    # via the setgid /run/mrcalld dir) can connect — independent of the
    # process umask. Mirrors server_ws.py's post-bind chmod.
    os.chmod(socket_path, 0o660)
    logger.info(f"[provisiond] serving on unix:{socket_path}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        try:
            os.unlink(socket_path)
        except OSError:
            pass
        logger.info("[provisiond] stopped")


if __name__ == "__main__":
    main()
