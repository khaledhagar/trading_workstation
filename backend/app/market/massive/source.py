"""MassiveSource: real prices from the Massive REST API, in one of two modes.

snapshot  (Starter and above)  one snapshot call per poll for all tracked tickers
eod       (free Basic plan)    end-of-day closes from the grouped-daily endpoint,
                               refreshed every 30 min, calls spaced ≥ 12 s apart

The mode is detected from the first snapshot call (403 → eod) unless forced.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable, Iterable
from datetime import date, datetime
from typing import Literal

import httpx

from ..base import MarketDataSource
from ..cache import PriceCache
from ..errors import MarketDataUnavailableError, UnknownTickerError
from .client import (
    BASE_URL,
    MassiveClient,
    MassiveError,
    PlanNotEntitledError,
    RateLimitedError,
)
from .parse import NY, last_weekday_on_or_before, market_close_utc, parse_snapshot, previous_weekday

logger = logging.getLogger(__name__)

Mode = Literal["snapshot", "eod"]
PROBE_TICKER = "AAPL"


class MassiveSource(MarketDataSource):
    def __init__(
        self,
        cache: PriceCache,
        api_key: str,
        *,
        mode: Mode | None = None,            # None = auto-detect
        poll_interval: float = 15.0,         # snapshot mode
        eod_refresh: float = 1800.0,         # eod mode
        error_backoff: float = 60.0,         # after 429s, failed detection and eod failures
        free_tier_spacing: float = 12.0,     # 5 calls/min
        ready_timeout: float = 20.0,         # longest an add waits for the first load
        eod_max_calls: int = 5,
        base_url: str = BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
        today: Callable[[], date] | None = None,
    ) -> None:
        super().__init__(cache)
        if mode not in (None, "snapshot", "eod"):
            raise ValueError(f"Invalid Massive mode: {mode!r}")
        self._api_key = api_key
        self._mode: Mode | None = mode
        self._poll_interval = poll_interval
        self._eod_refresh = eod_refresh
        self._error_backoff = error_backoff
        self._free_tier_spacing = free_tier_spacing
        self._ready_timeout = ready_timeout
        self._eod_max_calls = eod_max_calls
        self._base_url = base_url
        self._transport = transport
        self._today = today or (lambda: datetime.now(NY).date())

        self._tickers: set[str] = set()
        self._latest: dict[str, float] = {}      # eod: whole-market closes, latest day
        self._previous: dict[str, float] = {}    # eod: whole-market closes, day before
        self._latest_day: date | None = None
        self._ready = asyncio.Event()            # set after the first successful load
        self._client: MassiveClient | None = None
        self._task: asyncio.Task | None = None

    @property
    def mode(self) -> Mode | None:
        return self._mode

    @property
    def client(self) -> MassiveClient:
        if self._client is None:
            raise RuntimeError("MassiveSource.start() has not been called")
        return self._client

    # --- MarketDataSource ----------------------------------------------------
    async def start(self, tickers: Iterable[str]) -> None:
        self._tickers = set(tickers)
        if self._client is None:
            spacing = 0.0 if self._mode == "snapshot" else self._free_tier_spacing
            self._client = MassiveClient(
                self._api_key, base_url=self._base_url, transport=self._transport, min_interval=spacing
            )
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="massive-poller")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    async def add_ticker(self, ticker: str) -> None:
        if ticker in self._tickers:                              # C3
            return
        if self._mode is None or (self._mode == "eod" and self._latest_day is None):
            await self._wait_ready()

        if self._mode == "snapshot":
            snaps = await self.client.snapshots([ticker])        # 1 call
            parsed = parse_snapshot(snaps[ticker]) if ticker in snaps else None
            if parsed is None:
                raise UnknownTickerError(ticker)
            self.cache.update(ticker, parsed.price, parsed.reference, parsed.timestamp)
        else:
            if ticker not in self._latest:                       # 0 calls
                raise UnknownTickerError(ticker)
            self._write_eod(ticker)
        self._tickers.add(ticker)                                # C2: cache already seeded

    async def remove_ticker(self, ticker: str) -> None:
        self._tickers.discard(ticker)
        self.cache.remove(ticker)                                # C4

    def tracked_tickers(self) -> frozenset[str]:
        return frozenset(self._tickers)

    # --- background loop -------------------------------------------------------
    async def _run(self) -> None:
        while True:
            try:
                await self._poll_once()
                delay = self._eod_refresh if self._mode == "eod" else self._poll_interval
            except asyncio.CancelledError:
                raise
            except RateLimitedError:
                logger.warning("Massive rate limit hit; backing off %.0fs", self._error_backoff)
                delay = self._error_backoff
            except Exception as exc:                             # C5
                if isinstance(exc, MassiveError):
                    logger.error("Massive poll failed: %s. Keeping last prices.", exc)
                else:
                    logger.exception("Massive poll failed unexpectedly. Keeping last prices.")
                # Snapshot mode is unmetered, so retry on the normal cadence;
                # detection and eod mode may be on the 5-calls/min free plan, so back off.
                delay = self._poll_interval if self._mode == "snapshot" else self._error_backoff
            await asyncio.sleep(delay)

    async def _poll_once(self) -> None:
        if self._mode is None:
            await self._detect_mode()
        elif self._mode == "snapshot":
            await self._poll_snapshot()
        else:
            await self._refresh_eod()

    async def _detect_mode(self) -> None:
        probe = sorted(self._tickers) or [PROBE_TICKER]          # never send an empty filter
        try:
            snaps = await self.client.snapshots(probe)
        except PlanNotEntitledError:
            logger.warning(
                "Massive plan has no snapshot access; using end-of-day prices "
                "(refreshed every %.0f min)", self._eod_refresh / 60
            )
            self._mode = "eod"
            await self._refresh_eod()
            return
        self._mode = "snapshot"
        self.client.min_interval = 0.0                           # paid plans are unlimited
        logger.info("Massive snapshot mode: polling every %.0fs", self._poll_interval)
        self._apply_snapshots(snaps)
        self._ready.set()

    async def _poll_snapshot(self) -> None:
        tickers = frozenset(self._tickers)
        if tickers:
            self._apply_snapshots(await self.client.snapshots(tickers))
        self._ready.set()

    def _apply_snapshots(self, snaps: dict[str, dict]) -> None:
        for ticker, snap in snaps.items():
            if ticker not in self._tickers:                      # removed during the await (C4)
                continue
            parsed = parse_snapshot(snap)
            if parsed is not None:                               # else keep the last price
                self.cache.update(ticker, parsed.price, parsed.reference, parsed.timestamp)

    # --- eod mode ----------------------------------------------------------------
    async def _refresh_eod(self) -> None:
        (latest_day, latest), previous = await self._latest_two_closes()
        self._latest, self._previous, self._latest_day = latest, previous, latest_day
        for ticker in sorted(self._tickers):                     # no awaits in this loop
            if ticker in latest:
                self._write_eod(ticker)
            else:
                logger.warning("No end-of-day data for tracked ticker %s", ticker)
        self._ready.set()
        logger.info("Massive end-of-day prices loaded for %s", latest_day.isoformat())

    async def _latest_two_closes(self) -> tuple[tuple[date, dict[str, float]], dict[str, float]]:
        """Walk back from today: weekends are skipped for free; holidays, unpublished days
        and 403s for not-yet-available dates cost one call each and are skipped."""
        day = last_weekday_on_or_before(self._today())
        found: list[tuple[date, dict[str, float]]] = []
        for _ in range(self._eod_max_calls):
            try:
                closes = await self.client.grouped_daily(day)
            except PlanNotEntitledError:
                closes = {}                                      # e.g. today, before it's published
            if closes:
                found.append((day, closes))
                if len(found) == 2:
                    return found[0], found[1][1]
            day = previous_weekday(day)
        raise MassiveError("Could not find two trading days of end-of-day data")

    def _write_eod(self, ticker: str) -> None:
        assert self._latest_day is not None
        self.cache.update(
            ticker,
            self._latest[ticker],
            self._previous.get(ticker),
            market_close_utc(self._latest_day),
        )

    async def _wait_ready(self) -> None:
        try:
            await asyncio.wait_for(self._ready.wait(), self._ready_timeout)
        except TimeoutError:
            raise MarketDataUnavailableError("Market data is still loading") from None
