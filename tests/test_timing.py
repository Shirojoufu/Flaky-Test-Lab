"""Flaky: timing assertion. A stalled runner blows the 100 ms budget."""

import time

from lab.timing import process


def test_batch_within_latency_budget():
    start = time.perf_counter()
    process(range(1000))

    assert time.perf_counter() - start < 0.1
