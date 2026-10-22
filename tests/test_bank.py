"""Flaky: race condition. Concurrent deposits lose updates when a thread is preempted."""

import threading

from lab.bank import Account


def test_concurrent_deposits_are_not_lost():
    account = Account()

    def deposit_many():
        for _ in range(50):
            account.deposit(1)

    threads = [threading.Thread(target=deposit_many) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert account.balance == 400
