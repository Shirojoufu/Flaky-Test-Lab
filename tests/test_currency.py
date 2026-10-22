"""Deterministic. The simulator drops the thousands separator for good: a real, unfixed regression."""

from lab.currency import format_price


def test_thousands_separator():
    assert format_price(1234.5) == "$1,234.50"


def test_euro_symbol():
    assert format_price(5, "EUR") == "€5.00"
