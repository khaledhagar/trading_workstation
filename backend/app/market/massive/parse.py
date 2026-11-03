import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

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


def ns_to_datetime(ns: object) -> datetime | None:
    if isinstance(ns, bool) or not isinstance(ns, (int, float)) or ns <= 0:
        return None
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)


def parse_snapshot(snap: dict, now: datetime | None = None) -> ParsedPrice | None:
    """One element of the snapshot `tickers[]` array → price, reference, timestamp."""

    def field(obj: str, key: str) -> float | None:
        return _positive((snap.get(obj) or {}).get(key))

    price = (
        field("lastTrade", "p")
        or field("min", "c")
        or field("day", "c")
        or field("prevDay", "c")
    )
    if price is None:
        return None
    timestamp = ns_to_datetime(snap.get("updated")) or now or datetime.now(timezone.utc)
    return ParsedPrice(price=price, reference=field("prevDay", "c"), timestamp=timestamp)


def parse_grouped(data: dict) -> dict[str, float]:
    """Grouped-daily response → {ticker: close}. Empty dict for a day with no data."""
    closes: dict[str, float] = {}
    for row in data.get("results") or []:
        ticker, close = row.get("T"), _positive(row.get("c"))
        if isinstance(ticker, str) and close is not None:
            closes[ticker] = close
    return closes


def last_weekday_on_or_before(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def previous_weekday(d: date) -> date:
    return last_weekday_on_or_before(d - timedelta(days=1))


def market_close_utc(d: date) -> datetime:
    """16:00 New York time on `d`, as UTC (handles daylight saving)."""
    return datetime.combine(d, time(16, 0), tzinfo=NY).astimezone(timezone.utc)
