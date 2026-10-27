"""Pure parsing of Massive responses and trading-day helpers. No I/O."""

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from ..cache import is_priceable

NY = ZoneInfo("America/New_York")


@dataclass(frozen=True, slots=True)
class ParsedPrice:
    price: float
    reference: float | None
    timestamp: datetime


def _positive(value: object) -> float | None:
    """float(value) if it's a finite number > 0, else None (Massive uses 0 for 'missing')."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _price(value: object) -> float | None:
    """Like _positive, but also rejects prices that round below one cent (the cache's minimum)."""
    number = _positive(value)
    return number if number is not None and is_priceable(number) else None


def ns_to_datetime(ns: object) -> datetime | None:
    """Unix nanoseconds (the snapshot `updated` field) → aware UTC datetime."""
    if isinstance(ns, bool) or not isinstance(ns, (int, float)) or not math.isfinite(ns) or ns <= 0:
        return None
    try:
        return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


# Snapshot price fields, in fallback order (MASSIVE_API.md §2.1).
PRICE_FIELDS = (("lastTrade", "p"), ("min", "c"), ("day", "c"), ("prevDay", "c"))


def _field(snap: dict, obj: str, key: str) -> object:
    section = snap.get(obj)
    return section.get(key) if isinstance(section, dict) else None


def parse_snapshot(snap: dict, now: datetime | None = None) -> ParsedPrice | None:
    """One element of the snapshot `tickers[]` array → price, reference, timestamp.

    Price is the first value ≥ 1 cent of lastTrade.p → min.c → day.c → prevDay.c;
    reference is prevDay.c. Returns None when no usable price exists: during the
    3:30–4:00 AM ET daily reset (see has_price_data) or for a sub-cent stock."""
    for obj, key in PRICE_FIELDS:
        price = _price(_field(snap, obj, key))
        if price is not None:
            break
    else:
        return None
    timestamp = ns_to_datetime(snap.get("updated")) or now or datetime.now(timezone.utc)
    return ParsedPrice(
        price=price, reference=_positive(_field(snap, "prevDay", "c")), timestamp=timestamp
    )


def has_price_data(snap: dict) -> bool:
    """False when every price field is missing or zero, which is what Massive returns
    while it resets snapshots (3:30–4:00 AM ET). Tells "try again later" apart from
    "this ticker has a price, but it's below one cent"."""
    return any(_positive(_field(snap, obj, key)) is not None for obj, key in PRICE_FIELDS)


def parse_grouped(data: dict) -> dict[str, float]:
    """Grouped-daily response → {ticker: close}. Empty dict for a day with no data.
    Rows closing below one cent are skipped, so those tickers count as unknown."""
    closes: dict[str, float] = {}
    results = data.get("results") if isinstance(data, dict) else None
    for row in results if isinstance(results, list) else []:
        if not isinstance(row, dict):
            continue
        ticker, close = row.get("T"), _price(row.get("c"))
        if isinstance(ticker, str) and ticker and close is not None:
            closes[ticker] = close
    return closes


# --- trading-day helpers -----------------------------------------------------
def last_weekday_on_or_before(d: date) -> date:
    while d.weekday() >= 5:            # Sat=5, Sun=6
        d -= timedelta(days=1)
    return d


def previous_weekday(d: date) -> date:
    return last_weekday_on_or_before(d - timedelta(days=1))


def market_close_utc(d: date) -> datetime:
    """16:00 New York time on `d`, as UTC (handles daylight saving)."""
    return datetime.combine(d, time(16, 0), tzinfo=NY).astimezone(timezone.utc)
