"""Flaky: order dependence. One test leaks global state; the other fails whenever it runs after it."""

from lab import settings


def test_configure_currency():
    settings.configure(currency="EUR")  # never reset: pollutes every later test

    assert settings.get("currency") == "EUR"


def test_default_currency():
    assert settings.get("currency") == "USD"
