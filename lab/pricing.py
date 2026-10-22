"""Discounts."""

from __future__ import annotations


def apply_discount(price: float, percent: float) -> float:
    return round(price * (1 - percent / 100), 2)
