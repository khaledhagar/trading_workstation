"""Thin async HTTP layer over the two Massive endpoints the app needs (MASSIVE_API.md §2.1, §2.3)."""

import asyncio
import time
from collections.abc import Iterable
from datetime import date

import httpx

from ..errors import MarketDataUnavailableError
from .parse import parse_grouped

BASE_URL = "https://api.massive.com"
SNAPSHOT_PATH = "/v2/snapshot/locale/us/markets/stocks/tickers"
GROUPED_PATH = "/v2/aggs/grouped/locale/us/market/stocks/{day}"


class MassiveError(MarketDataUnavailableError):
    """Any failure talking to Massive. Subclass of MarketDataUnavailableError → 503."""


class MassiveAuthError(MassiveError):        # 401: missing / invalid key
    pass


class PlanNotEntitledError(MassiveError):    # 403: endpoint or date not in the plan
    pass


class RateLimitedError(MassiveError):        # 429
    pass


class MassiveClient:
    """No automatic retries: the next poll is the retry, so a 429 never multiplies.

    The key goes only in the Authorization header, so it never appears in URLs,
    logs or exception messages. Errors branch on the status code, never the message text.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
        min_interval: float = 0.0,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=timeout,
            transport=transport,
        )
        self.min_interval = min_interval     # seconds between calls; 12.0 on the free plan
        self._last_call: float | None = None
        self._spacing = asyncio.Lock()
        self.calls = 0                       # handy for logs and tests

    async def snapshots(self, tickers: Iterable[str]) -> dict[str, dict]:
        """Paid plans. {ticker: raw snapshot}. Unknown tickers are simply absent."""
        wanted = sorted(set(tickers))
        if not wanted:                       # an empty filter means "whole market": never send it
            return {}
        data = await self._get(SNAPSHOT_PATH, {"tickers": ",".join(wanted)})
        rows = data.get("tickers")
        return {
            s["ticker"]: s
            for s in (rows if isinstance(rows, list) else [])
            if isinstance(s, dict) and isinstance(s.get("ticker"), str) and s["ticker"]
        }

    async def grouped_daily(self, day: date) -> dict[str, float]:
        """All plans. {ticker: close} for every US stock on `day`; {} if no data."""
        data = await self._get(GROUPED_PATH.format(day=day.isoformat()), {"adjusted": "true"})
        return parse_grouped(data)

    async def aclose(self) -> None:
        await self._http.aclose()

    # --- internals -----------------------------------------------------------
    async def _wait_for_slot(self) -> None:
        # Reserves a time slot, then releases the lock before the request,
        # so a slow response doesn't hold other callers up.
        async with self._spacing:
            if self.min_interval and self._last_call is not None:
                wait = self._last_call + self.min_interval - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
            self._last_call = time.monotonic()

    async def _get(self, path: str, params: dict[str, str]) -> dict:
        await self._wait_for_slot()
        self.calls += 1
        try:
            resp = await self._http.get(path, params=params)
        except httpx.HTTPError as exc:       # timeouts, DNS, connection resets
            raise MassiveError(f"Massive request failed: {type(exc).__name__}") from exc

        status = resp.status_code
        if status == 401:
            raise MassiveAuthError("Massive rejected the API key (401)")
        if status == 403:
            raise PlanNotEntitledError(f"Massive plan does not include {path} (403)")
        if status == 429:
            raise RateLimitedError("Massive rate limit exceeded (429)")
        if status >= 400:
            raise MassiveError(f"Massive returned HTTP {status} for {path}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise MassiveError("Massive returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise MassiveError("Massive returned an unexpected response shape")
        return data
