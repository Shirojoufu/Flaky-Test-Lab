"""Time-ordered IDs: milliseconds since the epoch plus a per-millisecond counter."""

from __future__ import annotations

import time

from . import chaos

# Rarely, NTP steps the clock back mid-run, and the generator revisits timestamps it already used.
CLOCK_STEPPED_BACK = chaos.fires("ids.clock_step_back", 0.03)


class IdGenerator:
    def __init__(self):
        self._last_ms = -1
        self._counter = 0
        self._skew_ms = 0

    def now_ms(self) -> int:
        return int(time.time() * 1000) + self._skew_ms

    def next_id(self) -> int:
        now_ms = self.now_ms()
        if now_ms == self._last_ms:
            self._counter += 1
        else:
            self._last_ms, self._counter = now_ms, 0  # assumes the clock never goes backwards
        return now_ms * 1000 + self._counter

    def step_clock_back(self, ms: int) -> None:
        self._skew_ms -= ms
