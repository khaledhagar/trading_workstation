import math
from datetime import datetime, timezone

from .models import PriceUpdate

# Smallest price the cache stores. Prices are rounded to cents, so anything that
# rounds below one cent would be stored as 0.00 and fill trades for free.
MIN_PRICE = 0.01


def is_priceable(value: object) -> bool:
    """True if `value` is a finite number that is still ≥ 1 cent after rounding to cents."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and round(value, 2) >= MIN_PRICE
    )


def _valid_reference(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


class PriceCache:
    """Latest price per tracked ticker. Written by exactly one source, read by everyone.

    All access happens on the event loop thread, so no locking is needed.
    The cache never invents a price: a missing ticker has no price yet.
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
        """Record a new price for `ticker`.

        - previous_price is the old entry's price (or the new price on the first write).
        - reference_price=None (or an unusable value) keeps the old reference;
          on the first write it defaults to the price.
        - Raises ValueError for a price that isn't a finite number of at least 1 cent
          after rounding, so the cache never holds a 0.00 price.
        """
        if not is_priceable(price):
            raise ValueError(f"Invalid price for {ticker}: {price!r}")
        if reference_price is not None and not _valid_reference(reference_price):
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
