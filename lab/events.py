"""Fan a request out to replicas and collect replies as they arrive."""

from __future__ import annotations

import asyncio

from . import chaos

# Replica response times vary with load; on a quiet day they arrive in request order.
JITTER = chaos.fires("events.jitter", 0.2)


async def _query(replica: str, delay: float) -> str:
    await asyncio.sleep(delay)
    return replica


async def collect(replicas: list[str]) -> list[str]:
    jitter = chaos.rng("events.delays")
    delays = [0.01 * (i + 1) + (jitter.uniform(0, 0.05) if JITTER else 0) for i in range(len(replicas))]
    replies = []
    for reply in asyncio.as_completed([_query(r, d) for r, d in zip(replicas, delays)]):
        replies.append(await reply)
    return replies
