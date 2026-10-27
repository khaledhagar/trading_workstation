"""Tickers, errors, PriceUpdate and PriceCache."""

import math
from datetime import datetime, timedelta, timezone

import pytest

import app.market as market
from app.market import (
    InvalidTickerError,
    MarketDataUnavailableError,
    PriceCache,
    UnknownTickerError,
    normalize_ticker,
)
from app.market.cache import is_priceable
from app.market.errors import MarketDataError
from app.market.models import PriceUpdate, format_timestamp

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


# --- tickers -------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw, expected",
    [(" aapl ", "AAPL"), ("brk.b", "BRK.B"), ("V", "V"), ("\tmsft\n", "MSFT"), ("ABCDEFGHIJ", "ABCDEFGHIJ")],
)
def test_normalize_ok(raw, expected):
    assert normalize_ticker(raw) == expected


@pytest.mark.parametrize(
    "raw", ["", "  ", "1ABC", ".AB", "ABCDEFGHIJK", "TOOLONGTICKER", "AA-PL", "AA PL", "ÄPPL", None, 5, b"AAPL"]
)
def test_normalize_rejects(raw):
    with pytest.raises(InvalidTickerError, match="Invalid ticker") as info:
        normalize_ticker(raw)
    assert info.value.raw == raw


# --- errors --------------------------------------------------------------------
def test_error_messages_and_hierarchy():
    assert str(UnknownTickerError("XYZ")) == "Unknown ticker: XYZ"
    assert UnknownTickerError("XYZ").ticker == "XYZ"
    assert issubclass(InvalidTickerError, ValueError)
    assert issubclass(UnknownTickerError, LookupError)
    for exc in (InvalidTickerError, UnknownTickerError, MarketDataUnavailableError):
        assert issubclass(exc, MarketDataError)


def test_public_api():
    for name in market.__all__:
        assert hasattr(market, name)


# --- models --------------------------------------------------------------------
def test_timestamp_format_has_millis_and_z():
    assert format_timestamp(datetime(2026, 1, 1, 12, 0, 0, 500_000, tzinfo=timezone.utc)) == "2026-01-01T12:00:00.500Z"
    assert format_timestamp(NOW) == "2026-01-01T12:00:00.000Z"


def test_timestamp_converts_other_zones_to_utc():
    cairo = timezone(timedelta(hours=2))
    assert format_timestamp(datetime(2026, 1, 1, 14, 0, tzinfo=cairo)) == "2026-01-01T12:00:00.000Z"


@pytest.mark.parametrize(
    "price, previous, direction", [(191.0, 190.0, "up"), (189.0, 190.0, "down"), (190.0, 190.0, "flat")]
)
def test_direction(price, previous, direction):
    assert PriceUpdate("AAPL", price, previous, 190.0, NOW).direction == direction


def test_change_percent():
    assert PriceUpdate("AAPL", 191.9, 190.0, 190.0, NOW).change_percent == 1.0
    assert PriceUpdate("AAPL", 188.1, 190.0, 190.0, NOW).change_percent == -1.0
    assert PriceUpdate("AAPL", 190.0, 190.0, 0.0, NOW).change_percent == 0.0   # guarded


def test_change_percent_never_negative_zero():
    pct = PriceUpdate("ZZZ", 231.64, 231.65, 231.65, NOW).change_percent
    assert pct == 0.0 and math.copysign(1, pct) == 1.0


def test_to_dict_has_exact_contract_fields():
    d = PriceUpdate("AAPL", 191.9, 190.0, 190.0, NOW).to_dict()
    assert d == {
        "ticker": "AAPL",
        "price": 191.9,
        "previous_price": 190.0,
        "timestamp": "2026-01-01T12:00:00.000Z",
        "direction": "up",
        "change_percent": 1.0,
    }


def test_price_update_is_immutable():
    u = PriceUpdate("AAPL", 1.0, 1.0, 1.0, NOW)
    with pytest.raises(AttributeError):
        u.price = 2.0  # type: ignore[misc]


# --- cache ---------------------------------------------------------------------
def test_cache_first_write():
    cache = PriceCache()
    first = cache.update("AAPL", 190.0)
    assert (first.price, first.previous_price, first.reference_price) == (190.0, 190.0, 190.0)
    assert first.direction == "flat" and first.change_percent == 0.0
    assert first.timestamp.tzinfo is not None


def test_cache_chains_previous_and_keeps_reference():
    cache = PriceCache()
    cache.update("AAPL", 190.0, reference_price=190.0)
    second = cache.update("AAPL", 189.504)
    assert second.price == 189.5 and second.previous_price == 190.0
    assert second.reference_price == 190.0 and second.direction == "down"
    third = cache.update("AAPL", 190.123)
    assert third.previous_price == 189.5 and third.change_percent == 0.06


def test_cache_replaces_reference_when_given():
    cache = PriceCache()
    cache.update("AAPL", 190.0, reference_price=188.0)
    assert cache.update("AAPL", 191.0, reference_price=190.0).reference_price == 190.0


@pytest.mark.parametrize("bad_ref", [0.0, -1.0, math.nan, math.inf])
def test_cache_ignores_unusable_reference(bad_ref):
    cache = PriceCache()
    cache.update("AAPL", 190.0, reference_price=185.0)
    assert cache.update("AAPL", 191.0, reference_price=bad_ref).reference_price == 185.0
    assert PriceCache().update("MSFT", 50.0, reference_price=bad_ref).reference_price == 50.0


def test_cache_sub_cent_move_is_flat():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    assert cache.update("AAPL", 190.004).direction == "flat"


@pytest.mark.parametrize("bad", [0.0, -5.0, math.nan, math.inf, None, "190", True, 0.004, 0.0049])
def test_cache_rejects_bad_price(bad):
    cache = PriceCache()
    with pytest.raises(ValueError):
        cache.update("AAPL", bad)  # type: ignore[arg-type]
    assert "AAPL" not in cache


def test_cache_never_stores_a_zero_price():
    # 0.004 is > 0 but rounds to 0.00, which would fill trades for free.
    cache = PriceCache()
    cache.update("ABCW", 0.02)
    with pytest.raises(ValueError):
        cache.update("ABCW", 0.004)
    assert cache.get_price("ABCW") == 0.02                  # last good price kept
    assert cache.update("XYZ", 0.005).price == 0.01         # rounds up to one cent: accepted


@pytest.mark.parametrize("value, ok", [(0.01, True), (0.005, True), (0.0049, False), (0.0, False),
                                       (190.0, True), (math.nan, False), (True, False), ("1", False)])
def test_is_priceable(value, ok):
    assert is_priceable(value) is ok


def test_cache_uses_given_timestamp():
    assert PriceCache().update("AAPL", 1.0, timestamp=NOW).timestamp == NOW


def test_cache_get_remove_len_contains():
    cache = PriceCache()
    assert cache.get("AAPL") is None and cache.get_price("AAPL") is None and len(cache) == 0
    cache.update("AAPL", 1.0)
    cache.update("MSFT", 2.0)
    assert "AAPL" in cache and len(cache) == 2 and cache.get_price("MSFT") == 2.0
    cache.remove("AAPL")
    cache.remove("NOPE")                     # no-op
    assert "AAPL" not in cache and cache.get_price("AAPL") is None and len(cache) == 1


def test_cache_snapshot_is_a_copy():
    cache = PriceCache()
    cache.update("AAPL", 1.0)
    snap = cache.snapshot()
    cache.update("MSFT", 2.0)
    cache.remove("AAPL")
    assert set(snap) == {"AAPL"}
