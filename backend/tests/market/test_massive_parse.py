import math
from datetime import date, datetime, timezone

import pytest

from app.market.massive.parse import (
    _positive,
    has_price_data,
    last_weekday_on_or_before,
    market_close_utc,
    ns_to_datetime,
    parse_grouped,
    parse_snapshot,
    previous_weekday,
)

NOW = datetime(2026, 10, 18, 19, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "value, expected",
    [(1.5, 1.5), (2, 2.0), ("3.5", 3.5), (0, None), (-1, None), (None, None),
     (True, None), ("abc", None), (math.nan, None), (math.inf, None), ({}, None)],
)
def test_positive(value, expected):
    assert _positive(value) == expected


def test_fallback_chain():
    assert parse_snapshot({"lastTrade": {"p": 10.0}, "min": {"c": 9.0}}).price == 10.0
    assert parse_snapshot({"lastTrade": {"p": 0}, "min": {"c": 9.0}}).price == 9.0
    assert parse_snapshot({"min": {"c": 0}, "day": {"c": 8.0}, "prevDay": {"c": 7.0}}).price == 8.0
    only_prev = parse_snapshot({"day": {"c": 0}, "prevDay": {"c": 7.0}})
    assert only_prev.price == 7.0 and only_prev.reference == 7.0


def test_design_example():
    p = parse_snapshot({
        "ticker": "AAPL",
        "min": {"c": 190.5},
        "day": {"c": 190.4},
        "prevDay": {"c": 188.0},
        "lastTrade": {"p": 0},          # missing on Starter → zero → skipped
        "updated": 1_700_000_000_000_000_000,
    })
    assert p.price == 190.5 and p.reference == 188.0
    assert p.timestamp == datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)


def test_docs_sample_response_element():
    # MASSIVE_API.md §2.1 sample
    snap = {
        "ticker": "BCAT",
        "day": {"o": 20.64, "h": 20.64, "l": 20.506, "c": 20.506, "v": 37216, "vw": 20.616},
        "min": {"o": 20.506, "c": 20.506, "t": 1684428600000},
        "prevDay": {"o": 20.79, "c": 20.63},
        "lastTrade": {"p": 20.506, "s": 2416, "t": 1605192894630916600},
        "updated": 1605192894630916600,
    }
    p = parse_snapshot(snap)
    assert p.price == 20.506 and p.reference == 20.63
    assert p.timestamp.year == 2020


def test_nothing_usable():
    assert parse_snapshot({"ticker": "X", "day": {"c": 0}}) is None
    assert parse_snapshot({}) is None


def test_sub_cent_values_are_skipped_in_the_fallback_chain():
    p = parse_snapshot({"lastTrade": {"p": 0.004}, "min": {"c": 0.02}, "prevDay": {"c": 0.03}})
    assert p.price == 0.02 and p.reference == 0.03
    assert parse_snapshot({"min": {"c": 0.004}, "prevDay": {"c": 0.003}}) is None


@pytest.mark.parametrize("snap, expected", [
    ({"min": {"c": 0}, "day": {"c": 0}, "prevDay": {"c": 0}}, False),   # daily reset
    ({}, False),
    ({"lastTrade": None, "min": "x"}, False),
    ({"min": {"c": 0.004}}, True),                                      # sub-cent, but priced
    ({"prevDay": {"c": 7.0}}, True),
])
def test_has_price_data(snap, expected):
    assert has_price_data(snap) is expected


def test_parse_grouped_skips_sub_cent_closes():
    data = {"results": [{"T": "AAPL", "c": 190.0}, {"T": "ABCDW", "c": 0.004}, {"T": "PNNY", "c": 0.005}]}
    assert parse_grouped(data) == {"AAPL": 190.0, "PNNY": 0.005}


def test_missing_reference():
    p = parse_snapshot({"min": {"c": 5.0}})
    assert p.price == 5.0 and p.reference is None


def test_tolerates_malformed_sections():
    assert parse_snapshot({"lastTrade": None, "min": [1, 2], "day": "x", "prevDay": {"c": 7.0}}).price == 7.0


def test_timestamp_fallbacks():
    assert parse_snapshot({"min": {"c": 1.0}}, now=NOW).timestamp == NOW
    assert parse_snapshot({"min": {"c": 1.0}, "updated": 0}, now=NOW).timestamp == NOW
    default = parse_snapshot({"min": {"c": 1.0}})
    assert default.timestamp.tzinfo is not None


@pytest.mark.parametrize("ns", [None, 0, -5, True, "123", math.nan, 10**30])
def test_ns_to_datetime_rejects(ns):
    assert ns_to_datetime(ns) is None


def test_ns_to_datetime():
    assert ns_to_datetime(1_700_000_000_500_000_000) == datetime(2023, 11, 14, 22, 13, 20, 500_000, tzinfo=timezone.utc)


def test_parse_grouped_skips_bad_rows():
    data = {"results": [{"T": "AAPL", "c": 190.0}, {"T": "BAD", "c": 0}, {"c": 5.0},
                        {"T": 7, "c": 1.0}, {"T": "", "c": 1.0}, "junk", {"T": "MSFT", "c": "420.5"}]}
    assert parse_grouped(data) == {"AAPL": 190.0, "MSFT": 420.5}


@pytest.mark.parametrize("data", [{"resultsCount": 0}, {"results": None}, {"results": []}, {"results": "x"}, []])
def test_parse_grouped_empty(data):
    assert parse_grouped(data) == {}


def test_trading_days():
    assert last_weekday_on_or_before(date(2026, 10, 18)) == date(2026, 10, 16)   # Sun → Fri
    assert last_weekday_on_or_before(date(2026, 10, 17)) == date(2026, 10, 16)   # Sat → Fri
    assert last_weekday_on_or_before(date(2026, 10, 14)) == date(2026, 10, 14)   # Wed stays
    assert previous_weekday(date(2026, 10, 19)) == date(2026, 10, 16)            # Mon → Fri
    assert previous_weekday(date(2026, 10, 15)) == date(2026, 10, 14)            # Thu → Wed


def test_market_close_handles_daylight_saving():
    assert market_close_utc(date(2026, 10, 16)) == datetime(2026, 10, 16, 20, 0, tzinfo=timezone.utc)  # EDT
    assert market_close_utc(date(2026, 12, 15)) == datetime(2026, 12, 15, 21, 0, tzinfo=timezone.utc)  # EST
