"""Batch processing with a latency budget."""

from __future__ import annotations

import time

from . import chaos

# Shared CI runners: a noisy neighbour, a GC pause or CPU throttling stalls the process.
STALLED = chaos.fires("timing.stall", 0.08)


def process(batch) -> list[int]:
    if STALLED:
        time.sleep(0.2)
    return [x * 2 for x in batch]
