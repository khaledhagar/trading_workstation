import asyncio
import math
import random
from datetime import datetime, timezone

import httpx
import pytest

from app.market import (
    InvalidTickerError,
    MarketDataUnavailableError,
    PriceCache,
    UnknownTickerError,
    create_market_data_source,
    normalize_ticker,
    price_events,
)
from app.market.massive.parse import parse_grouped, parse_snapshot, previous_weekday
from app.market.massive.source import MassiveSource
from app.market.models import format_timestamp
from app.market.simulator.engine import SimulatorEngine
from app.market.simulator.source import SimulatorSource


# --- tickers & cache ----------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [("aapl", "AAPL"), ("  brk.b ", "BRK.B"), ("V", "V")])
def test_normalize_ok(raw, expected):
    assert normalize_ticker(raw) == expected


@pytest.mark.parametrize("raw", ["", "12AB", ".A", "ABCDEFGHIJK", "AA-B", None, 5])
def test_normalize_rejects(raw):
    with pytest.raises(InvalidTickerError):
        normalize_ticker(raw)


def test_cache_chain_and_change_percent():
    cache = PriceCache()
    cache.update("AAPL", 190.0, reference_price=190.0)
    e = cache.update("AAPL", 190.123)
    assert e.price == 190.12 and e.previous_price == 190.0
    assert e.direction == "up" and e.change_percent == 0.06
    e = cache.update("AAPL", 189.0)
    assert e.direction == "down" and e.reference_price == 190.0


def test_cache_rejects_bad_prices():
    cache = PriceCache()
    for bad in (0, -1, math.inf, math.nan):
        with pytest.raises(ValueError):
            cache.update("X", bad)


def test_timestamp_has_millis_and_z():
    ts = datetime(2026, 1, 1, 12, 0, 0, 500000, tzinfo=timezone.utc)
    assert format_timestamp(ts) == "2026-01-01T12:00:00.500Z"


# --- simulator ----------------------------------------------------------------

def test_engine_prices_positive_and_deterministic():
    a, b = SimulatorEngine(random.Random(1)), SimulatorEngine(random.Random(1))
    for e in (a, b):
        e.add("AAPL"), e.add("TSLA"), e.add("ZZZ")
    for _ in range(500):
        pa, pb = a.step(), b.step()
        assert pa == pb
        assert all(p > 0 for p in pa.values())


def test_engine_unknown_ticker_seed_range():
    e = SimulatorEngine(random.Random(3))
    seed = e.add("QQQQ")
    assert 50 <= seed <= 300
    assert e.profile("QQQQ").sector is None


def test_engine_gbm_drift_free_mean():
    # With zero vol the step is exactly exp(mu*dt).
    e = SimulatorEngine(random.Random(0), event_mean_seconds=math.inf)
    e.add("AAPL")
    st = e._states["AAPL"]
    from app.market.simulator.seeds import TickerProfile
    st.profile = TickerProfile(100.0, 0.1, 0.0, None)
    st.price = 100.0
    e.step()
    assert st.price == pytest.approx(100.0 * math.exp(0.1 * e.dt))


def test_engine_sector_correlation():
    e = SimulatorEngine(random.Random(42), event_mean_seconds=math.inf)
    for t in ("AAPL", "MSFT", "JPM"):
        e.add(t)
    prev = {t: e._states[t].price for t in ("AAPL", "MSFT", "JPM")}
    r = {t: [] for t in prev}
    for _ in range(4000):
        out = e.step()
        for t in prev:
            r[t].append(math.log(out[t] / prev[t]))
            prev[t] = out[t]

    def corr(x, y):
        mx, my = sum(x) / len(x), sum(y) / len(y)
        cov = sum((a - mx) * (b - my) for a, b in zip(x, y))
        return cov / math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))

    assert corr(r["AAPL"], r["MSFT"]) == pytest.approx(0.6, abs=0.06)
    assert corr(r["AAPL"], r["JPM"]) == pytest.approx(0.3, abs=0.06)


async def test_simulator_source_contract():
    cache = PriceCache()
    sim = SimulatorSource(cache, interval=0.01, rng=random.Random(7))
    await sim.start(["AAPL"])
    assert "AAPL" in cache and cache.get("AAPL").price == 190.0
    await sim.add_ticker("PYPL")
    assert "PYPL" in cache
    await asyncio.sleep(0.05)
    await sim.remove_ticker("PYPL")
    assert "PYPL" not in cache
    await asyncio.sleep(0.05)
    assert "PYPL" not in cache
    await sim.stop()
    await sim.stop()  # idempotent


def test_factory_selects_source():
    cache = PriceCache()
    assert isinstance(create_market_data_source(cache, {}), SimulatorSource)
    src = create_market_data_source(cache, {"MASSIVE_API_KEY": "k", "MASSIVE_MODE": "bogus"})
    assert isinstance(src, MassiveSource) and src.mode is None


# --- massive ------------------------------------------------------------------

def test_parse_snapshot_fallback_chain():
    p = parse_snapshot({"ticker": "AAPL", "min": {"c": 190.5}, "day": {"c": 190.4},
                        "prevDay": {"c": 188.0}, "lastTrade": {"p": 0},
                        "updated": 1_700_000_000_000_000_000})
    assert p.price == 190.5 and p.reference == 188.0
    assert parse_snapshot({"ticker": "X"}) is None


def test_parse_grouped_and_weekdays():
    from datetime import date
    assert parse_grouped({"results": [{"T": "A", "c": 1.5}, {"T": "B", "c": 0}]}) == {"A": 1.5}
    assert previous_weekday(date(2026, 10, 19)) == date(2026, 10, 16)  # Monday → Friday


def _transport(handler):
    return httpx.MockTransport(handler)


async def test_massive_snapshot_mode():
    def handler(req: httpx.Request):
        tickers = req.url.params["tickers"].split(",")
        known = [t for t in tickers if t != "NOPE"]
        return httpx.Response(200, json={"tickers": [
            {"ticker": t, "lastTrade": {"p": 100.0}, "prevDay": {"c": 99.0}} for t in known]})

    cache = PriceCache()
    src = MassiveSource(cache, "k", transport=_transport(handler), poll_interval=0.01)
    await src.start(["AAPL"])
    await src.add_ticker("MSFT")
    assert src.mode == "snapshot" and cache.get("MSFT").change_percent == 1.01
    with pytest.raises(UnknownTickerError):
        await src.add_ticker("NOPE")
    await src.stop()


async def test_massive_eod_mode_on_403():
    def handler(req: httpx.Request):
        if "snapshot" in req.url.path:
            return httpx.Response(403, json={})
        day = req.url.path.rsplit("/", 1)[-1]
        closes = {"2026-10-16": 110.0, "2026-10-15": 100.0}
        if day not in closes:
            return httpx.Response(403, json={})
        return httpx.Response(200, json={"results": [{"T": "AAPL", "c": closes[day]},
                                                     {"T": "PYPL", "c": 70.0}]})

    from datetime import date
    cache = PriceCache()
    src = MassiveSource(cache, "k", transport=_transport(handler), free_tier_spacing=0,
                        today=lambda: date(2026, 10, 18))
    await src.start(["AAPL"])
    await src.add_ticker("PYPL")        # waits for readiness, then 0 calls
    assert src.mode == "eod"
    assert cache.get("AAPL").price == 110.0 and cache.get("AAPL").change_percent == 10.0
    with pytest.raises(UnknownTickerError):
        await src.add_ticker("ZZZZ")
    await src.stop()


async def test_massive_add_times_out_when_provider_down():
    cache = PriceCache()
    src = MassiveSource(cache, "k", transport=_transport(lambda r: httpx.Response(500)),
                        ready_timeout=0.05, poll_interval=10)
    await src.start([])
    with pytest.raises(MarketDataUnavailableError):
        await src.add_ticker("AAPL")
    await src.stop()


# --- SSE ------------------------------------------------------------------------

async def test_price_events_format():
    class Req:
        n = 0

        async def is_disconnected(self):
            self.n += 1
            return self.n > 2

    cache = PriceCache()
    cache.update("AAPL", 190.0)
    events = [e async for e in price_events(cache, Req(), interval=0)]
    assert events[0] == "retry: 2000\n\n"
    assert events[1].startswith('data: {"AAPL":{"ticker":"AAPL","price":190.0')
    assert len(events) == 3
