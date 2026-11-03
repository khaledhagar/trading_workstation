import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable

from .cache import PriceCache
from .errors import MarketDataUnavailableError, UnknownTickerError

logger = logging.getLogger(__name__)


class MarketDataSource(ABC):
    """Prices a set of tracked tickers and writes them into a PriceCache."""

    def __init__(self, cache: PriceCache) -> None:
        self.cache = cache

    @abstractmethod
    async def start(self, tickers: Iterable[str]) -> None:
        """Begin tracking `tickers` and launch the background task. Returns quickly."""

    @abstractmethod
    async def stop(self) -> None:
        """Cancel the background task and release resources. Idempotent."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Start tracking `ticker`. When this returns, the cache has a price for it.
        Raises UnknownTickerError or MarketDataUnavailableError. No-op if already tracked."""

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Stop tracking `ticker` and remove it from the cache. No-op if not tracked."""

    @abstractmethod
    def tracked_tickers(self) -> frozenset[str]:
        """The tickers currently being priced."""

    async def sync_tickers(self, desired: Iterable[str]) -> None:
        """Make the tracked set equal `desired` (watchlist ∪ positions). Add failures are logged."""
        desired = set(desired)
        current = self.tracked_tickers()
        for ticker in current - desired:
            await self.remove_ticker(ticker)
        for ticker in desired - current:
            try:
                await self.add_ticker(ticker)
            except (UnknownTickerError, MarketDataUnavailableError) as exc:
                logger.warning("Could not track %s: %s", ticker, exc)
