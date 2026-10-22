"""Bank account with an unsynchronised read-modify-write: the classic lost-update race."""

from __future__ import annotations

import time

from . import chaos

# On a busy machine the scheduler sometimes preempts a thread between the read and the write.
PREEMPTED = chaos.fires("bank.preemption", 0.3)


class Account:
    def __init__(self, balance: int = 0):
        self.balance = balance

    def deposit(self, amount: int) -> None:
        current = self.balance
        if PREEMPTED:
            time.sleep(0.0005)  # another thread deposits here, and its update is lost
        self.balance = current + amount
