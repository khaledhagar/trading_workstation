from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

Direction = Literal["up", "down", "flat"]


def format_timestamp(ts: datetime) -> str:
    """ISO 8601 UTC with milliseconds and a Z suffix: 2026-01-01T12:00:00.500Z."""
    return ts.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    ticker: str
    price: float            # rounded to 2 decimals
    previous_price: float   # price before this update (== price on the first update)
    reference_price: float  # baseline for change %: seed price (simulator) or previous close (Massive)
    timestamp: datetime     # timezone-aware UTC

    @property
    def direction(self) -> Direction:
        # Compares rounded prices (what the user sees), so a sub-cent move is "flat".
        if self.price > self.previous_price:
            return "up"
        if self.price < self.previous_price:
            return "down"
        return "flat"

    @property
    def change_percent(self) -> float:
        if self.reference_price <= 0:
            return 0.0
        # "+ 0.0" turns -0.0 (a tiny loss rounded away) into 0.0, so the UI never shows "-0.00%".
        return round((self.price - self.reference_price) / self.reference_price * 100, 2) + 0.0

    def to_dict(self) -> dict:
        """The exact field set of an SSE entry and a GET /api/watchlist row (PLAN.md §6, §8).
        reference_price is internal and deliberately left out."""
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "timestamp": format_timestamp(self.timestamp),
            "direction": self.direction,
            "change_percent": self.change_percent,
        }
