"""Stock reservations. The lock makes check-then-reserve atomic."""

from __future__ import annotations

import threading
import time

from . import chaos

# A slow stock lookup widens the window between checking stock and reserving it.
SLOW_LOOKUP = chaos.fires("inventory.slow_lookup", 0.35)


class OutOfStock(Exception):
    pass


class Inventory:
    def __init__(self, stock: dict[str, int]):
        self._stock = dict(stock)
        self._lock = threading.Lock()

    def reserve(self, sku: str, quantity: int = 1) -> None:
        with self._lock:
            available = self._stock.get(sku, 0)
            if SLOW_LOOKUP:
                time.sleep(0.002)
            if available < quantity:
                raise OutOfStock(sku)
            self._stock[sku] = available - quantity

    def available(self, sku: str) -> int:
        return self._stock.get(sku, 0)
