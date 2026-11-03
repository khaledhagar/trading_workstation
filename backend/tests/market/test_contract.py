"""One suite, both sources: the MarketDataSource behaviour contract (C1–C6).

C3 and C5 need source-specific setup and also live in test_massive_source.py /
test_simulator_source.py.
"""

import asyncio
import random

import pytest

from app.market import MarketDataSource, PriceCache
from app.market.massive.source import MassiveSource
from app.market.simulator.source import SimulatorSource

from .fakes import FakeMassive, wait_until


@pytest.fixture(params=["simulator", "massive"])
async def source(request):
    cache = PriceCache()
    if request.param == "simulator":
        src = SimulatorSource(cache, interval=0.01, rng=random.Random(42))
    else:
        src = MassiveSource(cache, "test-key", mode="snapshot", poll_interval=0.01,
                            transport=FakeMassive().transport)
    yield src
    await src.stop()


def test_is_a_market_data_source(source):
    assert isinstance(source, MarketDataSource)


async def test_c1_start_prices_tickers(source):
    await source.start(["AAPL", "MSFT"])
    await wait_until(lambda: "AAPL" in source.cache and "MSFT" in source.cache)
    assert source.tracked_tickers() == frozenset({"AAPL", "MSFT"})


async def test_c1_start_with_nothing_tracked(source):
    await source.start([])
    await asyncio.sleep(0.03)
    assert len(source.cache) == 0 and source.tracked_tickers() == frozenset()


async def test_c2_add_seeds_cache_before_returning(source):
    await source.start(["AAPL"])
    await source.add_ticker("PYPL")
    assert "PYPL" in source.cache
    assert source.cache.get_price("PYPL") > 0
    assert "PYPL" in source.tracked_tickers()


async def test_c3_add_twice_is_a_no_op(source):
    await source.start(["AAPL"])
    await source.add_ticker("PYPL")
    await source.add_ticker("PYPL")
    assert source.tracked_tickers() == frozenset({"AAPL", "PYPL"})


async def test_c4_remove_stops_writes(source):
    await source.start(["AAPL", "MSFT"])
    await wait_until(lambda: "MSFT" in source.cache)
    await source.remove_ticker("MSFT")
    await asyncio.sleep(0.05)                     # several ticks/polls
    assert "MSFT" not in source.cache
    assert "MSFT" not in source.tracked_tickers()
    assert "AAPL" in source.cache


async def test_c4_remove_untracked_is_a_no_op(source):
    await source.start(["AAPL"])
    await source.remove_ticker("NOPE")
    assert source.tracked_tickers() == frozenset({"AAPL"})


async def test_prices_keep_updating(source):
    await source.start(["AAPL"])
    await wait_until(lambda: "AAPL" in source.cache)
    first = source.cache.get("AAPL")
    await wait_until(lambda: source.cache.get("AAPL") is not first)


async def test_c6_stop_is_idempotent_and_ends_the_task(source):
    await source.start(["AAPL"])
    task = source._task
    await source.stop()
    await source.stop()
    assert task.done() and source._task is None
    frozen = source.cache.get("AAPL")
    await asyncio.sleep(0.03)
    assert source.cache.get("AAPL") is frozen     # nothing writes after stop


async def test_stop_before_start(source):
    await source.stop()


async def test_sync_tickers_adds_and_removes(source):
    await source.start(["AAPL", "MSFT"])
    await wait_until(lambda: "MSFT" in source.cache)
    await source.sync_tickers({"AAPL", "PYPL"})
    assert source.tracked_tickers() == frozenset({"AAPL", "PYPL"})
    assert "PYPL" in source.cache and "MSFT" not in source.cache
