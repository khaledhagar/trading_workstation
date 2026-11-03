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
        self.interval = interval
        self.engine = engine or SimulatorEngine(rng, tick_seconds=interval, time_scale=time_scale)
        self._task: asyncio.Task | None = None

    async def start(self, tickers: Iterable[str]) -> None:
        for ticker in tickers:
            self._seed(ticker)
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="market-simulator")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def add_ticker(self, ticker: str) -> None:
        if ticker not in self.engine.tickers():
            self._seed(ticker)

    async def remove_ticker(self, ticker: str) -> None:
        self.engine.remove(ticker)
        self.cache.remove(ticker)

    def tracked_tickers(self) -> frozenset[str]:
        return self.engine.tickers()

    def _seed(self, ticker: str) -> None:
        seed = self.engine.add(ticker)
        self.cache.update(ticker, seed, reference_price=seed)

    def _tick(self) -> None:
        for ticker, price in self.engine.step().items():
            self.cache.update(ticker, price)

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        next_tick = loop.time()
        while True:
            try:
                self._tick()
            except Exception:
                logger.exception("Simulator tick failed")
            next_tick += self.interval
            now = loop.time()
            if next_tick < now:  # fell behind (e.g. laptop sleep); don't burst
                next_tick = now
            await asyncio.sleep(next_tick - now)
