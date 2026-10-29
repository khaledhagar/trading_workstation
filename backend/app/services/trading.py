"""Trade execution shared by the trade bar and the chat flow (PLAN.md §8 Trading Rules)."""

from typing import Literal

import db
from app.market import normalize_ticker

from .portfolio import build_portfolio
from .watchlist import add_ticker, resync_market


async def trade(state, raw_ticker, side: Literal["buy", "sell"], quantity: float) -> dict:
    """Returns {"trade": ..., "portfolio": ...}.

    A buy auto-adds the ticker to the watchlist first (same validation and cache seeding as
    POST /api/watchlist). A sell resyncs afterwards, so a full exit of an unwatched ticker
    stops tracking it. Raises InvalidTickerError / UnknownTickerError / TradeError /
    MarketDataUnavailableError."""
    ticker = normalize_ticker(raw_ticker)
    if side not in ("buy", "sell"):
        raise ValueError(f"Invalid side: {side!r}")
    if side == "buy":
        await add_ticker(state, ticker)     # idempotent; no-op if already watched
    cache = state.price_cache
    with db.connect() as conn:
        executed = db.execute_trade(conn, ticker=ticker, side=side, quantity=quantity,
                                    get_price=cache.get_price)
    if side == "sell":
        await resync_market(state)
    with db.connect() as conn:
        return {"trade": executed, "portfolio": build_portfolio(conn, cache)}
