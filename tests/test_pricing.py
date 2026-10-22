"""Deterministic. The simulator breaks apply_discount for a while, then fixes it: a real regression."""

from lab.pricing import apply_discount


def test_discount():
    assert apply_discount(80, 25) == 60.0


def test_no_discount():
    assert apply_discount(19.99, 0) == 19.99
