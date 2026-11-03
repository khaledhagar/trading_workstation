import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable

from .cache import PriceCache
from .errors import MarketDataUnavailableError, UnknownTickerError

logger = logging.getLogger(__name__)


class MarketDataSource(ABC):
    """Prices a set of tracked tickers and writes them into a PriceCache.

    Behaviour contract (MARKET_DATA_DESIGN.md §4), shared by every implementation:

    C1  After `await start(ts)`, every ticker the source can price appears in the cache
        within one tick (simulator: immediately) or one poll (Massive).
    C2  After `await add_ticker(t)` returns, `t in cache` is True.
    C3  `add_ticker(t)` for an already-tracked `t` returns immediately, with no network call.
    C4  After `await remove_ticker(t)`, `t not in cache`, and the background task never
        writes `t` again.
    C5  The background task survives errors: a failed tick/poll is logged, the last
        prices stay, the loop continues.
    C6  `stop()` is idempotent and leaves no running task.
    C7  A ticker's reference price is stable for the life of the process (simulator)
        or the trading day (Massive).
    C8  Sources never touch the database.
    """

    def __init__(self, cache: PriceCache) -> None:
        self.cache = cache

    @abstractmethod
    async def start(self, tickers: Iterable[str]) -> None:
        """Begin tracking `tickers` and launch the background task.
        Returns quickly (no slow network work). Called once, from the lifespan handler."""

    @abstractmethod
    async def stop(self) -> None:
        """Cancel the background task and release resources. Idempotent."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Start tracking `ticker`. When this returns, the cache HAS a price for it.
        Raises UnknownTickerError if the source can't price it,
        MarketDataUnavailableError if the source can't answer right now.
        No-op (and no network call) if already tracked."""

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Stop tracking `ticker` and remove it from the cache. No-op if not tracked."""

    @abstractmethod
    def tracked_tickers(self) -> frozenset[str]:
        """The tickers currently being priced."""

    async def sync_tickers(self, desired: Iterable[str]) -> None:
        """Make the tracked set equal `desired` (the DB's watchlist ∪ positions).

        Missing tickers are added; failures are logged, not raised, because these tickers
        are already persisted and the user shouldn't get an error for an unrelated request."""
        desired = set(desired)
        current = self.tracked_tickers()
        for ticker in current - desired:
            await self.remove_ticker(ticker)
        for ticker in sorted(desired - current):
            try:
                await self.add_ticker(ticker)
            except (UnknownTickerError, MarketDataUnavailableError) as exc:
                logger.warning("Could not track %s: %s", ticker, exc)
