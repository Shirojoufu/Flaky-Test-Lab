"""A service that binds its port only after warming up, and a client that doesn't retry."""

from __future__ import annotations

import socket
import threading
import time

from . import chaos

# Some starts are cold: loading config and warming caches takes longer than the caller waits.
COLD_START = chaos.fires("service.cold_start", 0.3)
READY_WAIT = 0.05  # "should be plenty"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class EchoService:
    def __init__(self, warmup: float | None = None):
        self.port = free_port()
        self.warmup = warmup if warmup is not None else (0.3 if COLD_START else 0.0)
        self._listening = threading.Event()

    def start(self) -> EchoService:
        threading.Thread(target=self._serve, daemon=True).start()
        self._listening.wait(READY_WAIT)
        return self

    def _serve(self) -> None:
        time.sleep(self.warmup)
        with socket.create_server(("127.0.0.1", self.port)) as server:
            self._listening.set()
            server.settimeout(2)
            try:
                conn, _ = server.accept()
            except TimeoutError:
                return
            with conn:
                conn.sendall(conn.recv(1024).upper())


def call(port: int, message: str, timeout: float = 0.2) -> str:
    # Linux refuses a connection to a port nobody listens on yet; Windows keeps retrying the SYN
    # for ~2 s, so there the short timeout is what makes a cold start fail.
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as conn:
        conn.sendall(message.encode())
        return conn.recv(1024).decode()
