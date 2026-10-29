"""Business logic shared by the REST routes and the chat flow (TEAM_CONTRACTS.md §3)."""

from .portfolio import build_portfolio
from .trading import trade
from .watchlist import NotInWatchlistError, add_ticker, remove_ticker, resync_market, watchlist_rows

__all__ = [
    "build_portfolio",
    "trade",
    "NotInWatchlistError",
    "add_ticker",
    "remove_ticker",
    "resync_market",
    "watchlist_rows",
]
