import asyncio
import random

import pytest

from app.market import PriceCache
from app.market.simulator.engine import SimulatorEngine
from app.market.simulator.source import SimulatorSource

from .fakes import wait_until


def simulator(**kw) -> SimulatorSource:
    return SimulatorSource(PriceCache(), interval=0.01, rng=random.Random(1), **kw)


async def test_start_seeds_synchronously_at_reference():
    src = simulator()
    await src.start(["AAPL", "TSLA"])
    e = src.cache.get("AAPL")
    assert (e.price, e.previous_price, e.reference_price) == (190.0, 190.0, 190.0)
    assert e.change_percent == 0.0 and e.direction == "flat"
    await src.stop()


async def test_reference_stays_at_seed_after_ticks():
    src = simulator(time_scale=1000)
    await src.start(["AAPL"])
    await asyncio.sleep(0.1)
    e = src.cache.get("AAPL")
    assert e.reference_price == 190.0
    assert e.change_percent == round((e.price - 190.0) / 190.0 * 100, 2)
    await src.stop()


async def test_unknown_ticker_gets_random_seed():
    src = simulator()
    await src.start([])
    await src.add_ticker("ZZZ")
    assert 50.0 <= src.cache.get_price("ZZZ") <= 300.0
    await src.stop()


async def test_add_existing_does_not_reseed():
    src = simulator(time_scale=1000)
    await src.start(["AAPL"])
    await wait_until(lambda: src.cache.get_price("AAPL") != 190.0)
    moved = src.cache.get_price("AAPL")
    await src.stop()                               # freeze prices
    await src.add_ticker("AAPL")
    assert src.cache.get_price("AAPL") == moved


async def test_remove_then_add_reseeds():
    src = simulator(time_scale=1000)
    await src.start(["AAPL"])
    await wait_until(lambda: src.cache.get_price("AAPL") != 190.0)
    await src.remove_ticker("AAPL")
    await src.add_ticker("AAPL")
    assert src.cache.get("AAPL").reference_price == 190.0
    await src.stop()


async def test_start_twice_keeps_one_task():
    src = simulator()
    await src.start(["AAPL"])
    task = src._task
    await src.start(["MSFT"])
    assert src._task is task
    assert src.tracked_tickers() == frozenset({"AAPL", "MSFT"})
    await src.stop()


async def test_second_start_keeps_reference_and_price():
    src = simulator()
    await src.start(["TSLA"])
    await wait_until(lambda: src.cache.get("TSLA").price != 250.0)
    before = src.cache.get("TSLA")
    await src.start(["TSLA"])
    after = src.cache.get("TSLA")
    assert after.reference_price == 250.0                   # C7: still the seed
    assert after is before                                  # not re-seeded
    await src.stop()


async def test_ticks_at_fixed_cadence():
    src = SimulatorSource(PriceCache(), interval=0.02, rng=random.Random(1))
    calls = {"n": 0}
    real_tick = src._tick

    def counting_tick():
        calls["n"] += 1
        real_tick()

    src._tick = counting_tick
    await src.start(["AAPL"])
    await asyncio.sleep(0.2)
    await src.stop()
    assert 6 <= calls["n"] <= 14                   # ~10 at 20 ms (loose for CI timers)


async def test_c5_tick_errors_dont_kill_loop(monkeypatch):
    src = simulator()
    await src.start(["AAPL"])
    real_step, calls = src.engine.step, {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return real_step()

    monkeypatch.setattr(src.engine, "step", flaky)
    first = src.cache.get("AAPL")
    await wait_until(lambda: calls["n"] > 3)
    assert src.cache.get("AAPL") is not first
    await src.stop()


async def test_injected_engine_is_used():
    engine = SimulatorEngine(random.Random(3), tick_seconds=0.01)
    src = SimulatorSource(PriceCache(), interval=0.01, engine=engine)
    await src.start(["AAPL"])
    assert engine.tickers() == frozenset({"AAPL"})
    await src.stop()


def test_rejects_bad_interval():
    with pytest.raises(ValueError):
        SimulatorSource(PriceCache(), interval=0)
