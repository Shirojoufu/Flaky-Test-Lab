"""Price-quote client, and a stand-in upstream server whose latency varies with congestion."""

from __future__ import annotations

import socket
import socketserver
import threading
import time

from . import chaos

CONGESTED = chaos.fires("network.congestion", 0.3)
CLIENT_TIMEOUT = 0.25


def fetch_quote(host: str, port: int, symbol: str, timeout: float = CLIENT_TIMEOUT) -> float:
    with socket.create_connection((host, port), timeout=timeout) as conn:
        conn.sendall(f"{symbol}\n".encode())
        reply = conn.makefile("r").readline()
    return float(reply)


class QuoteServer:
    """Answers ``SYMBOL\\n`` with a price after ``latency`` seconds."""

    PRICES = {"ACME": 101.5, "INITECH": 12.25}

    def __init__(self, latency: float | None = None):
        self.latency = latency if latency is not None else (0.6 if CONGESTED else 0.01)
        server = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                symbol = self.rfile.readline().decode().strip()
                time.sleep(server.latency)
                try:
                    self.wfile.write(f"{QuoteServer.PRICES[symbol]}\n".encode())
                except OSError:
                    pass  # the client gave up waiting

        self._server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True

    @property
    def address(self) -> tuple[str, int]:
        return self._server.server_address[:2]

    def __enter__(self) -> QuoteServer:
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()
