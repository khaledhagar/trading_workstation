"""Database path resolution, connections and startup initialization (PLAN.md §5, §7)."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
# backend/db/connection.py -> parents[2] is the project root (parent of backend/)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "db" / "trading_workstation.db"

DEFAULT_USER = "default"
DEFAULT_CASH = 10000.0
DEFAULT_TICKERS = ("AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX")
BUSY_TIMEOUT_MS = 5000


def utc_now_iso() -> str:
    """Current UTC time as ISO 8601 with whole seconds and a Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_ms(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def utc_now_iso_ms() -> str:
    """Current UTC time with milliseconds (keeps insertion order of rows made in the same second)."""
    return iso_ms(datetime.now(timezone.utc))


def get_db_path() -> Path:
    """`DB_PATH` env var if set and non-empty, else `<project root>/db/trading_workstation.db`."""
    raw = os.environ.get("DB_PATH", "").strip()
    if raw:
        return Path(raw).expanduser()
    return DEFAULT_DB_PATH


class _ClosingConnection(sqlite3.Connection):
    """sqlite3 connection whose context manager closes it (stdlib's only commits/rolls back)."""

    def __exit__(self, exc_type, exc, tb):
        try:
            if self.in_transaction:
                self.rollback()
        finally:
            self.close()
        return False


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open a short-lived connection: Row factory, busy_timeout 5000 ms, autocommit mode."""
    db_path = Path(path) if path is not None else get_db_path()
    conn = sqlite3.connect(
        db_path,
        factory=_ClosingConnection,
        isolation_level=None,  # autocommit; writes use explicit BEGIN IMMEDIATE
        check_same_thread=False,
        timeout=BUSY_TIMEOUT_MS / 1000,
    )
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    return conn


def init_db(path: Path | str | None = None) -> Path:
    """Create the parent dir, enable WAL, apply the schema, and seed defaults if needed.

    Seeding happens only when there is no "default" users_profile row, so existing data is never
    overwritten (even an emptied watchlist stays empty).
    """
    db_path = Path(path) if path is not None else get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute("BEGIN IMMEDIATE")
        try:
            exists = conn.execute(
                "SELECT 1 FROM users_profile WHERE id = ?", (DEFAULT_USER,)
            ).fetchone()
            if not exists:
                _seed(conn)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    return db_path


def _seed(conn: sqlite3.Connection) -> None:
    now = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?)",
        (DEFAULT_USER, DEFAULT_CASH, utc_now_iso()),
    )
    n = len(DEFAULT_TICKERS)
    # 1 ms apart (ending just before now) so "ORDER BY added_at" keeps the default order
    conn.executemany(
        "INSERT OR IGNORE INTO watchlist (user_id, ticker, added_at) VALUES (?, ?, ?)",
        [
            (DEFAULT_USER, t, iso_ms(now - timedelta(milliseconds=n - i)))
            for i, t in enumerate(DEFAULT_TICKERS)
        ],
    )
