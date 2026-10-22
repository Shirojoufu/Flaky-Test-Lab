import random

from lab import chaos


def pytest_collection_modifyitems(config, items):
    """Run tests in a random order each run, like pytest-randomly, so order dependencies surface."""
    random.Random(f"{chaos.SEED}:order").shuffle(items)


def pytest_report_header(config):
    return f"chaos seed: {chaos.SEED}"
