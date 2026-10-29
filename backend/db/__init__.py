"""SQLite persistence layer for trading_workstation (TEAM_CONTRACTS.md §2)."""

from .connection import (
    DEFAULT_CASH,
    DEFAULT_TICKERS,
    connect,
    get_db_path,
    init_db,
    utc_now_iso,
)
from .repository import (
    TradeError,
    add_watchlist,
    execute_trade,
    get_cash,
    get_position,
    insert_chat_message,
    insert_snapshot,
    list_chat_messages,
    list_positions,
    list_snapshots,
    list_watchlist,
    remove_watchlist,
    tracked_tickers,
)

__all__ = [
    "DEFAULT_CASH",
    "DEFAULT_TICKERS",
    "TradeError",
    "add_watchlist",
    "connect",
    "execute_trade",
    "get_cash",
    "get_db_path",
    "get_position",
    "init_db",
    "insert_chat_message",
    "insert_snapshot",
    "list_chat_messages",
    "list_positions",
    "list_snapshots",
    "list_watchlist",
    "remove_watchlist",
    "tracked_tickers",
    "utc_now_iso",
]
