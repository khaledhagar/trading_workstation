import asyncio
import json
from collections.abc import AsyncIterator
from typing import Protocol

from .cache import PriceCache


class _Disconnectable(Protocol):
    async def is_disconnected(self) -> bool: ...


async def price_events(
    cache: PriceCache, request: _Disconnectable, interval: float = 0.5
) -> AsyncIterator[str]:
    """PLAN.md §6: one unnamed event per tick, all tracked tickers keyed by ticker.

    Emits every `interval` even when nothing changed, which keeps the frontend's
    5-second staleness indicator green while Massive only updates every 15 s.
    Tickers with no price are absent from the cache, so they're omitted."""
    yield "retry: 2000\n\n"                      # browser reconnect delay after a drop
    while not await request.is_disconnected():
        payload = {ticker: entry.to_dict() for ticker, entry in cache.snapshot().items()}
        yield f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
        await asyncio.sleep(interval)
