"""Summaries of sensor readings."""

from __future__ import annotations


def high_readings(readings: list[float], threshold: float = 0.8) -> list[float]:
    return [r for r in readings if r > threshold]


def mean(values: list[float]) -> float:
    return sum(values) / len(values)
