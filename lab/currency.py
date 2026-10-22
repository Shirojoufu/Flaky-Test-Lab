"""Price formatting."""

from __future__ import annotations

SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£"}


def format_price(amount: float, currency: str = "USD") -> str:
    return f"{SYMBOLS[currency]}{amount:,.2f}"
