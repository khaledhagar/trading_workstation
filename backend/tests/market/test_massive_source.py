"""MassiveSource: mode detection, snapshot polling, end-of-day walk, error handling."""

import asyncio
import logging
from datetime import date

import pytest

from app.market import MarketDataUnavailableError, PriceCache, UnknownTickerError
from app.market.massive.client import SNAPSHOT_PATH
from app.market.massive.source import MassiveSource

from .fakes import FakeMassive, wait_until

SUNDAY = date(2026, 10, 18)
DAYS = {
    "2026-10-16": {"AAPL": 191.0, "MSFT": 421.0},
    "2026-10-15": {"AAPL": 189.0, "MSFT": 419.0},
}


def massive(fake: FakeMassive, **kw) -> MassiveSource:
    kw = {"free_tier_spacing": 0, "today": lambda: SUNDAY, **kw}
    return MassiveSource(PriceCache(), "test-key", transport=fake.transport, **kw)


# --- construction & lifecycle ----------------------------------------------------
def test_rejects_invalid_mode():
    with pytest.raises(ValueError):
        MassiveSource(PriceCache(), "k", mode="live")  # type: ignore[arg-type]


def test_client_before_start_raises():
    with pytest.raises(RuntimeError):
        _ = MassiveSource(PriceCache(), "k").client


async def test_stop_closes_http_client():
    src = massive(FakeMassive(), mode="snapshot", poll_interval=10)
    await src.start(["AAPL"])
    http = src.client._http
    await src.stop()
    assert http.is_closed
    with pytest.raises(RuntimeError):
        _ = src.client


async def test_start_returns_before_any_network_call():
    fake = FakeMassive()
    src = massive(fake, mode="snapshot", poll_interval=10)
    await src.start(["AAPL"])
    assert fake.requests == [] and "AAPL" not in src.cache
    await wait_until(lambda: "AAPL" in src.cache)
    await src.stop()


# --- snapshot mode ---------------------------------------------------------------
async def test_detects_snapshot_mode():
    fake = FakeMassive()
    src = massive(fake, poll_interval=0.01)
    await src.start(["AAPL"])
    await wait_until(lambda: "AAPL" in src.cache)
    assert src.mode == "snapshot"
    assert src.client.min_interval == 0.0          # paid plans: no spacing
    e = src.cache.get("AAPL")
    assert e.price == 190.0 and e.reference_price == 188.1
    await src.stop()


async def test_detection_with_nothing_tracked_probes_one_ticker():
    fake = FakeMassive()
    src = massive(fake, poll_interval=10)
    await src.start([])
    await wait_until(lambda: src.mode == "snapshot")
    assert fake.requests[0].url.params["tickers"] == "AAPL"    # never an empty filter
    assert len(src.cache) == 0                                 # probe result not written
    await src.stop()


async def test_one_call_per_poll_for_all_tickers():
    fake = FakeMassive()
    src = massive(fake, mode="snapshot", poll_interval=0.01)
    await src.start(["AAPL", "MSFT", "PYPL"])
    await wait_until(lambda: len(fake.requests) >= 3)
    await src.stop()
    for req in fake.requests:
        assert req.url.params["tickers"] == "AAPL,MSFT,PYPL"


async def test_poll_moves_prices_and_direction():
    fake = FakeMassive()
    src = massive(fake, mode="snapshot", poll_interval=0.01)
    await src.start(["AAPL"])
    await wait_until(lambda: "AAPL" in src.cache)
    fake.prices["AAPL"] = 191.5
    await wait_until(lambda: src.cache.get_price("AAPL") == 191.5)
    e = src.cache.get("AAPL")
    assert e.previous_price == 190.0 and e.direction == "up"
    await src.stop()


async def test_c3_add_tracked_ticker_makes_no_call():
    fake = FakeMassive()
    src = massive(fake, mode="snapshot", poll_interval=10)
    await src.start(["AAPL"])
    await wait_until(lambda: "AAPL" in src.cache)
    before = len(fake.requests)
    await src.add_ticker("AAPL")
    assert len(fake.requests) == before
    await src.stop()


async def test_snapshot_add_costs_one_call_and_seeds():
    fake = FakeMassive()
    src = massive(fake, mode="snapshot", poll_interval=10)
    await src.start(["AAPL"])
    await wait_until(lambda: "AAPL" in src.cache)
    before = len(fake.requests)
    await src.add_ticker("PYPL")
    assert len(fake.requests) == before + 1
    assert fake.requests[-1].url.params["tickers"] == "PYPL"
    e = src.cache.get("PYPL")
    assert e.price == 70.0 and e.reference_price == 69.3
    await src.stop()


async def test_snapshot_unknown_ticker_rejected():
    src = massive(FakeMassive(), mode="snapshot", poll_interval=10)
    await src.start([])
    with pytest.raises(UnknownTickerError, match="Unknown ticker: QWERTY"):
        await src.add_ticker("QWERTY")
    assert "QWERTY" not in src.tracked_tickers() and "QWERTY" not in src.cache
    await src.stop()


async def test_snapshot_add_with_no_usable_price_is_unknown():
    fake = FakeMassive()
    fake.raw_snapshots["DEAD"] = {"ticker": "DEAD", "day": {"c": 0}, "prevDay": {"c": 0}}
    src = massive(fake, mode="snapshot", poll_interval=10)
    await src.start([])
    with pytest.raises(UnknownTickerError):
        await src.add_ticker("DEAD")
    await src.stop()


async def test_snapshot_add_when_provider_down_is_unavailable():
    fake = FakeMassive()
    src = massive(fake, mode="snapshot", poll_interval=10)
    await src.start([])
    await wait_until(lambda: src._ready.is_set())
    fake.fail_next = 1
    with pytest.raises(MarketDataUnavailableError):
        await src.add_ticker("PYPL")
    assert "PYPL" not in src.tracked_tickers()
    await src.stop()


async def test_unusable_snapshot_keeps_last_price():
    fake = FakeMassive()
    src = massive(fake, mode="snapshot", poll_interval=10)
    await src.start(["AAPL"])
    await wait_until(lambda: "AAPL" in src.cache)
    src._apply_snapshots({"AAPL": {"ticker": "AAPL", "day": {"c": 0}}})
    assert src.cache.get_price("AAPL") == 190.0
    await src.stop()


async def test_snapshot_for_removed_ticker_is_ignored():
    src = massive(FakeMassive(), mode="snapshot", poll_interval=10)
    await src.start(["AAPL"])
    await wait_until(lambda: "AAPL" in src.cache)
    await src.remove_ticker("AAPL")
    src._apply_snapshots({"AAPL": {"ticker": "AAPL", "min": {"c": 200.0}}})   # late response
    assert "AAPL" not in src.cache
    await src.stop()


async def test_c5_poll_errors_keep_prices_and_loop_alive():
    fake = FakeMassive()
    src = massive(fake, mode="snapshot", poll_interval=0.01)
    await src.start(["AAPL"])
    await wait_until(lambda: "AAPL" in src.cache)
    fake.fail_next = 3
    n = len(fake.requests)
    await wait_until(lambda: len(fake.requests) > n + 4)       # kept polling through the 500s
    assert src.cache.get_price("AAPL") == 190.0
    await src.stop()


async def test_rate_limit_backs_off():
    fake = FakeMassive()
    src = massive(fake, mode="snapshot", poll_interval=0.01, error_backoff=10)
    await src.start(["AAPL"])
    await wait_until(lambda: "AAPL" in src.cache)
    fake.fail_status, fake.fail_next = 429, 1
    await wait_until(lambda: fake.fail_next == 0)
    n = len(fake.requests)
    await asyncio.sleep(0.1)
    assert len(fake.requests) == n                             # waiting out the backoff
    assert src.cache.get_price("AAPL") == 190.0
    await src.stop()


async def test_detection_error_stays_undetected_and_add_times_out():
    fake = FakeMassive()
    fake.fail_status, fake.fail_next = 401, 100
    src = massive(fake, ready_timeout=0.05, error_backoff=10)
    await src.start(["AAPL"])
    await wait_until(lambda: len(fake.requests) == 1)
    assert src.mode is None
    with pytest.raises(MarketDataUnavailableError):
        await src.add_ticker("MSFT")
    await src.stop()


async def test_add_waits_for_detection_then_succeeds():
    fake = FakeMassive()
    src = massive(fake, poll_interval=10)
    await src.start(["AAPL"])
    await src.add_ticker("PYPL")                               # waits for detection
    assert src.mode == "snapshot" and "PYPL" in src.cache
    await src.stop()


# --- eod mode ----------------------------------------------------------------------
async def test_free_plan_falls_back_to_eod():
    fake = FakeMassive(snapshot_status=403, days=DAYS)
    src = massive(fake)
    await src.start(["AAPL"])
    await wait_until(lambda: "AAPL" in src.cache)
    assert src.mode == "eod"
    e = src.cache.get("AAPL")
    assert (e.price, e.reference_price, e.change_percent) == (191.0, 189.0, 1.06)
    assert e.timestamp.isoformat() == "2026-10-16T20:00:00+00:00"
    assert e.to_dict()["timestamp"] == "2026-10-16T20:00:00.000Z"
    assert fake.paths()[0] == SNAPSHOT_PATH                    # probe, then Fri + Thu
    calls = len(fake.requests)
    assert calls == 3
    await src.add_ticker("MSFT")                               # 0 calls
    assert len(fake.requests) == calls
    assert src.cache.get("MSFT").reference_price == 419.0
    with pytest.raises(UnknownTickerError):
        await src.add_ticker("ZZZZ")
    await src.stop()


async def test_forced_eod_skips_the_probe():
    fake = FakeMassive(days=DAYS)
    src = massive(fake, mode="eod")
    await src.start(["AAPL"])
    await wait_until(lambda: "AAPL" in src.cache)
    assert SNAPSHOT_PATH not in fake.paths() and len(fake.requests) == 2
    await src.stop()


async def test_free_tier_spacing_applies_until_snapshot_detected():
    src = MassiveSource(PriceCache(), "k", transport=FakeMassive().transport)
    await src.start([])
    assert src.client.min_interval == 12.0
    await src.stop()
    forced = MassiveSource(PriceCache(), "k", mode="snapshot", transport=FakeMassive().transport)
    await forced.start([])
    assert forced.client.min_interval == 0.0
    await forced.stop()


async def test_eod_walk_skips_holiday_and_unpublished_today():
    days = {"2026-10-14": {"AAPL": 180.0}, "2026-10-13": {"AAPL": 178.0}}
    fake = FakeMassive(days=days, forbidden_days={"2026-10-16"})
    src = massive(fake, mode="eod", today=lambda: date(2026, 10, 16))
    await src.start(["AAPL"])
    await wait_until(lambda: "AAPL" in src.cache)
    # 16th: 403 (not yet published), 15th: empty (holiday), 14th + 13th: data
    assert [p.rsplit("/", 1)[-1] for p in fake.paths()] == [
        "2026-10-16", "2026-10-15", "2026-10-14", "2026-10-13"]
    assert src.cache.get("AAPL").reference_price == 178.0
    await src.stop()


async def test_eod_walk_skips_weekends_without_calls():
    days = {"2026-10-16": {"AAPL": 191.0}, "2026-10-15": {"AAPL": 189.0}}
    fake = FakeMassive(days=days)
    src = massive(fake, mode="eod", today=lambda: date(2026, 10, 17))   # Saturday
    await src.start(["AAPL"])
    await wait_until(lambda: "AAPL" in src.cache)
    assert [p.rsplit("/", 1)[-1] for p in fake.paths()] == ["2026-10-16", "2026-10-15"]
    await src.stop()


async def test_eod_walk_gives_up_after_max_calls():
    fake = FakeMassive(days={})
    src = massive(fake, mode="eod", eod_max_calls=3, error_backoff=10)
    await src.start(["AAPL"])
    await wait_until(lambda: len(fake.requests) == 3)
    await asyncio.sleep(0.03)
    assert len(fake.requests) == 3 and "AAPL" not in src.cache   # backing off, no more calls
    await src.stop()


async def test_add_before_ready_times_out_with_503_error():
    fake = FakeMassive(snapshot_status=403, days={})           # never becomes ready
    src = massive(fake, ready_timeout=0.05, error_backoff=10)
    await src.start([])
    with pytest.raises(MarketDataUnavailableError):
        await src.add_ticker("AAPL")
    await src.stop()


async def test_eod_refresh_is_flat_and_keeps_timestamp():
    fake = FakeMassive(days=DAYS)
    src = massive(fake, mode="eod", eod_refresh=0.01)
    await src.start(["AAPL"])
    await wait_until(lambda: len(fake.requests) >= 4)          # at least two refreshes
    e = src.cache.get("AAPL")
    assert e.direction == "flat" and e.price == e.previous_price == 191.0
    assert e.timestamp.isoformat() == "2026-10-16T20:00:00+00:00"
    await src.stop()


async def test_eod_refresh_picks_up_a_new_trading_day():
    days = dict(DAYS)
    today = {"value": date(2026, 10, 16)}
    fake = FakeMassive(days=days)
    src = massive(fake, mode="eod", eod_refresh=0.01, today=lambda: today["value"])
    await src.start(["AAPL"])
    await wait_until(lambda: "AAPL" in src.cache)
    fake.days["2026-10-19"] = {"AAPL": 195.0}
    today["value"] = date(2026, 10, 19)
    await wait_until(lambda: src.cache.get_price("AAPL") == 195.0)
    e = src.cache.get("AAPL")
    assert e.reference_price == 191.0 and e.direction == "up"
    await src.stop()


async def test_eod_failure_keeps_last_prices():
    fake = FakeMassive(days=DAYS)
    src = massive(fake, mode="eod", eod_refresh=0.01, error_backoff=0.01)
    await src.start(["AAPL"])
    await wait_until(lambda: "AAPL" in src.cache)
    fake.fail_next = 5
    await wait_until(lambda: fake.fail_next == 0)
    assert src.cache.get_price("AAPL") == 191.0
    await src.stop()


async def test_eod_tracked_ticker_without_data_is_logged(caplog):
    fake = FakeMassive(days=DAYS)
    src = massive(fake, mode="eod")
    with caplog.at_level(logging.WARNING, logger="app.market.massive.source"):
        await src.start(["AAPL", "GONE"])
        await wait_until(lambda: "AAPL" in src.cache)
    assert "GONE" not in src.cache
    assert any("GONE" in r.getMessage() for r in caplog.records)
    await src.stop()


# --- sync_tickers -------------------------------------------------------------------
async def test_sync_logs_failures_instead_of_raising(caplog):
    src = massive(FakeMassive(), mode="snapshot", poll_interval=10)
    await src.start(["AAPL"])
    with caplog.at_level(logging.WARNING, logger="app.market.base"):
        await src.sync_tickers({"AAPL", "QWERTY", "PYPL"})
    assert src.tracked_tickers() == frozenset({"AAPL", "PYPL"})
    assert any("QWERTY" in r.getMessage() for r in caplog.records)
    await src.stop()
