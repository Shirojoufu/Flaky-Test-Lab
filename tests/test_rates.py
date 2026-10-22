"""Deterministic, but depends on lab/data/rates.json. The simulator edits that file: a real
regression in a file coverage doesn't measure. The detector only gets it right because CI lists
lab/data/*.json in fingerprint-extra; without that, it would look flaky."""

from lab.rates import convert


def test_convert_to_euros():
    assert convert(100, "EUR") == 92.0
