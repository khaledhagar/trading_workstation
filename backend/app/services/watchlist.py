"""Watchlist operations and keeping the market source's tracked set in sync with the DB."""

import sqlite3

import db
from app.market import PriceCache, normalize_ticker


class NotInWatchlistError(LookupError):
    """DELETE of a ticker that isn't watched. API → 404."""

    def __init__(self, ticker: str) -> None:
        super().__init__(f"{ticker} is not in your watchlist")
        self.ticker = ticker


_EMPTY_PRICE = {"price": None, "previous_price": None, "direction": None,
                "change_percent": None, "timestamp": None}


def watchlist_rows(conn: sqlite3.Connection, cache: PriceCache) -> list[dict]:
    """GET /api/watchlist shape; price fields are null when the ticker has no price yet."""
    rows = []
    for ticker in db.list_watchlist(conn):
        entry = cache.get(ticker)
        rows.append(entry.to_dict() if entry else {"ticker": ticker, **_EMPTY_PRICE})
    return rows


async def add_ticker(state, raw_ticker) -> list[dict]:
    """Validate + seed via the market source first, so an unknown ticker is never persisted.
    Idempotent. Raises InvalidTickerError / UnknownTickerError / MarketDataUnavailableError."""
    ticker = normalize_ticker(raw_ticker)
    await state.market.add_ticker(ticker)
    with db.connect() as conn:
        db.add_watchlist(conn, ticker)
        return watchlist_rows(conn, state.price_cache)


async def remove_ticker(state, raw_ticker) -> list[dict]:
    """Remove from the watchlist (NotInWatchlistError if absent), then resync:
    a held ticker stays tracked so the position stays valued."""
    ticker = normalize_ticker(raw_ticker)
    with db.connect() as conn:
        if not db.remove_watchlist(conn, ticker):
            raise NotInWatchlistError(ticker)
    await resync_market(state)
    with db.connect() as conn:
        return watchlist_rows(conn, state.price_cache)


async def resync_market(state) -> None:
    """Make the source track exactly watchlist ∪ positions."""
    with db.connect() as conn:
        desired = db.tracked_tickers(conn)
    await state.market.sync_tickers(desired)
