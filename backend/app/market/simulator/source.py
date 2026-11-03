import asyncio
import contextlib
import logging
import random
from collections.abc import Iterable

from ..base import MarketDataSource
from ..cache import PriceCache
from .engine import SimulatorEngine

logger = logging.getLogger(__name__)


class SimulatorSource(MarketDataSource):
    """Default source: runs the GBM engine on a fixed 500 ms cadence and writes the cache."""

    def __init__(
        self,
        cache: PriceCache,
        *,
        interval: float = 0.5,
        rng: random.Random | None = None,
        time_scale: float = 1.0,
        engine: SimulatorEngine | None = None,
    ) -> None:
        super().__init__(cache)
        if interval <= 0:
            raise ValueError("interval must be > 0")
        self.interval = interval
        self.engine = engine or SimulatorEngine(rng, tick_seconds=interval, time_scale=time_scale)
        self._task: asyncio.Task | None = None

    async def start(self, tickers: Iterable[str]) -> None:
        for ticker in tickers:
            self._seed(ticker)                     # C1: priced before the first tick
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="market-simulator")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:                       # C6
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def add_ticker(self, ticker: str) -> None:
        if ticker not in self.engine.tickers():    # C3
            self._seed(ticker)                     # C2
        # Any well-formed ticker is accepted: the simulator never raises UnknownTickerError.

    async def remove_ticker(self, ticker: str) -> None:
        self.engine.remove(ticker)
        self.cache.remove(ticker)                  # C4

    def tracked_tickers(self) -> frozenset[str]:
        return self.engine.tickers()

    # --- internals -----------------------------------------------------------
    def _seed(self, ticker: str) -> None:
        seed = self.engine.add(ticker)
        self.cache.update(ticker, seed, reference_price=seed)   # change % starts at 0.00

    def _tick(self) -> None:
        for ticker, price in self.engine.step().items():
            self.cache.update(ticker, price)       # reference kept from the seed (C7)

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        next_tick = loop.time()
        while True:
            try:
                self._tick()                       # no awaits inside a tick
            except Exception:                      # C5
                logger.exception("Simulator tick failed")
            next_tick += self.interval
            now = loop.time()
            if next_tick < now:                    # fell behind (sleep, debugger): don't burst
                next_tick = now
            await asyncio.sleep(next_tick - now)
