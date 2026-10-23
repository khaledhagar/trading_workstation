"""Test doubles shared by the market tests. No network, no real clock beyond tiny sleeps."""

import asyncio
import time

import httpx

from app.market.massive.client import SNAPSHOT_PATH

FAKE_PRICES = {"AAPL": 190.0, "MSFT": 420.0, "PYPL": 70.0}


def make_snapshot(ticker: str, price: float) -> dict:
    return {
        "ticker": ticker,
        "min": {"c": price},
        "prevDay": {"c": round(price * 0.99, 2)},
        "updated": time.time_ns(),
    }


class FakeMassive:
    """httpx.MockTransport handler emulating Massive. Records every request.

    - `prices`: what the snapshot endpoint knows (absent tickers are omitted, like Massive)
    - `days`: {"YYYY-MM-DD": {ticker: close}} for the grouped-daily endpoint
    - `snapshot_status`: e.g. 403 to emulate the free plan
    - `forbidden_days`: dates that return 403 (not yet published on the free plan)
    - `fail_next`: the next N calls return `fail_status`
    """

    def __init__(
        self,
        prices: dict[str, float] | None = None,
        days: dict[str, dict[str, float]] | None = None,
        snapshot_status: int = 200,
        forbidden_days: set[str] = frozenset(),
    ):
        self.prices = dict(FAKE_PRICES if prices is None else prices)
        self.days = days or {}
        self.snapshot_status = snapshot_status
        self.forbidden_days = set(forbidden_days)
        self.raw_snapshots: dict[str, dict] = {}   # served verbatim, overriding `prices`
        self.requests: list[httpx.Request] = []
        self.fail_next = 0
        self.fail_status = 500

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail_next:
            self.fail_next -= 1
            return httpx.Response(self.fail_status, json={"status": "ERROR"})
        if request.url.path == SNAPSHOT_PATH:
            if self.snapshot_status != 200:
                return httpx.Response(self.snapshot_status, json={"status": "NOT_AUTHORIZED"})
            wanted = request.url.params.get("tickers", "").split(",")
            rows = [self.raw_snapshots[t] for t in wanted if t in self.raw_snapshots]
            rows += [make_snapshot(t, self.prices[t]) for t in wanted
                     if t in self.prices and t not in self.raw_snapshots]
            return httpx.Response(200, json={"status": "OK", "count": len(rows), "tickers": rows})
        if "/v2/aggs/grouped/" in request.url.path:
            day = request.url.path.rsplit("/", 1)[-1]
            if day in self.forbidden_days:
                return httpx.Response(403, json={"status": "NOT_AUTHORIZED"})
            rows = [{"T": t, "c": c} for t, c in self.days.get(day, {}).items()]
            return httpx.Response(200, json={"status": "OK", "resultsCount": len(rows), "results": rows})
        return httpx.Response(404, json={"status": "NOT_FOUND"})

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]


class FakeRequest:
    """Stands in for a Starlette Request: disconnects after `events` checks."""

    def __init__(self, events: int):
        self.remaining = events

    async def is_disconnected(self) -> bool:
        self.remaining -= 1
        return self.remaining < 0


async def wait_until(predicate, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.005)
