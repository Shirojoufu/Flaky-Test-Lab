"""Flaky: connection delay. A congested upstream answers after the client's 250 ms timeout."""

from lab.quotes import QuoteServer, fetch_quote


def test_fetch_quote():
    with QuoteServer() as server:
        assert fetch_quote(*server.address, "ACME") == 101.5
