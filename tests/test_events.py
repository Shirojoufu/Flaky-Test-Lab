"""Flaky: async ordering. Assumes replies arrive in request order; under load they don't."""

import asyncio

from lab.events import collect


def test_replies_in_request_order():
    assert asyncio.run(collect(["eu", "us", "ap", "sa"])) == ["eu", "us", "ap", "sa"]
