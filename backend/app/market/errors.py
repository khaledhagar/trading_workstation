"""Market-data exceptions and the HTTP status each one maps to (PLAN.md §8 Errors)."""


class MarketDataError(Exception):
    """Base class for market-data errors."""


class InvalidTickerError(MarketDataError, ValueError):
    """Fails the format rule (PLAN.md §6). API → 400 "Invalid ticker"."""

    def __init__(self, raw: object) -> None:
        super().__init__("Invalid ticker")
        self.raw = raw


class UnknownTickerError(MarketDataError, LookupError):
    """Well-formed, but the source has no data for it. API → 400 "Unknown ticker: XYZ"."""

    def __init__(self, ticker: str) -> None:
        super().__init__(f"Unknown ticker: {ticker}")
        self.ticker = ticker


class MarketDataUnavailableError(MarketDataError):
    """The source can't answer right now (still loading, provider down, rate limited).
    API → 503 "Market data unavailable, try again shortly"."""
