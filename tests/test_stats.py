"""Flaky: random test data. Sometimes no reading is high, and the mean divides by zero."""

from lab import chaos
from lab.stats import high_readings, mean


def test_mean_of_high_readings():
    readings = [chaos.rng("stats.readings").random() for _ in range(5)]

    assert 0.8 < mean(high_readings(readings)) <= 1.0
