"""Flaky: startup race. A cold start isn't listening yet when the client connects: connection refused."""

from lab.service import EchoService, call


def test_call_right_after_start():
    service = EchoService().start()

    assert call(service.port, "ping") == "PING"
