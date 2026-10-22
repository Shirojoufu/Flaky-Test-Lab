"""Stable while reserve() holds its lock. The simulator's "remove the lock" change makes it racy."""

import threading

import pytest

from lab.inventory import Inventory, OutOfStock


def test_concurrent_reservations_never_oversell():
    inventory = Inventory({"widget": 5})
    sold = []

    def buy():
        try:
            inventory.reserve("widget")
            sold.append(1)
        except OutOfStock:
            pass

    threads = [threading.Thread(target=buy) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(sold) == 5
    assert inventory.available("widget") == 0


def test_reserve_more_than_available():
    with pytest.raises(OutOfStock):
        Inventory({"widget": 1}).reserve("widget", 2)
