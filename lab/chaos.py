"""Seeded fault injection.

``CHAOS_SEED`` decides which faults are active in a test run: the same seed fires the same
faults, so the simulator can replay an exact history. Without ``CHAOS_SEED`` each run draws a
fresh seed, which is what makes the suite genuinely flaky in CI.

Faults only set up the conditions (a slow network, a dying node, a preempted thread). The
failures themselves are real: real sockets time out, real processes die, real threads race.
"""

from __future__ import annotations

import hashlib
import os
import random

SEED = os.environ.get("CHAOS_SEED") or f"random-{random.SystemRandom().getrandbits(64):x}"


def fires(fault: str, probability: float) -> bool:
    """Whether ``fault`` is active in this run."""
    digest = hashlib.sha256(f"{SEED}:{fault}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64 < probability


def rng(name: str) -> random.Random:
    """A random generator for this run, like unseeded ``random`` but replayable."""
    return random.Random(f"{SEED}:{name}")
