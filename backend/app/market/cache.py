import math
from datetime import datetime, timezone

from .models import PriceUpdate


class PriceCache:
    """Latest price per tracked ticker. Written by exactly one source, read by everyone.

    All access happens on the event loop thread, so no locking is needed.
    """

    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}

    def update(
        self,
        ticker: str,
        price: float,
        reference_price: float | None = None,
        timestamp: datetime | None = None,
    ) -> PriceUpdate:
        """Record a new price. reference_price=None keeps the old reference (or the price on first write)."""
        if not (math.isfinite(price) and price > 0):
            raise ValueError(f"Invalid price for {ticker}: {price!r}")
        if reference_price is not None and not (math.isfinite(reference_price) and reference_price > 0):
            reference_price = None

        old = self._prices.get(ticker)
        price = round(price, 2)
        if reference_price is None:
            reference_price = old.reference_price if old else price

        entry = PriceUpdate(
            ticker=ticker,
            price=price,
            previous_price=old.price if old else price,
            reference_price=reference_price,
            timestamp=timestamp or datetime.now(timezone.utc),
        )
        self._prices[ticker] = entry
        return entry

    def get(self, ticker: str) -> PriceUpdate | None:
        return self._prices.get(ticker)

    def get_price(self, ticker: str) -> float | None:
        entry = self._prices.get(ticker)
        return entry.price if entry else None

    def snapshot(self) -> dict[str, PriceUpdate]:
        """Shallow copy; safe to iterate while sources keep writing."""
        return dict(self._prices)

    def remove(self, ticker: str) -> None:
        self._prices.pop(ticker, None)

    def __contains__(self, ticker: object) -> bool:
        return ticker in self._prices

    def __len__(self) -> int:
        return len(self._prices)
