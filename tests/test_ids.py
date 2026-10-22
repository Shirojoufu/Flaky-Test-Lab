"""Flaky, but rarely (~3% of runs): IDs collide when the clock steps backwards."""

import time

from lab.ids import CLOCK_STEPPED_BACK, IdGenerator


def test_ids_are_unique():
    generator = IdGenerator()
    start_ms = generator.now_ms()
    ids = [generator.next_id() for _ in range(200)]
    time.sleep(0.005)
    ids += [generator.next_id() for _ in range(200)]
    if CLOCK_STEPPED_BACK:  # NTP correction lands back on a millisecond already used
        generator.step_clock_back(generator.now_ms() - start_ms)
    ids += [generator.next_id() for _ in range(200)]

    assert len(set(ids)) == len(ids)
