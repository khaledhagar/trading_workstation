"""Live terminal demo of the market data backend.

Runs the market data source chosen by the environment (the simulator by default, or
Massive when MASSIVE_API_KEY is set in the project's .env), reads prices through the
same SSE generator the frontend will use, and draws a live watchlist table.

    cd backend
    uv run python demo.py                    # the 10 default tickers
    uv run python demo.py --fast             # simulator at 60x speed: livelier moves
    uv run python demo.py PYPL brk.b ZZZ     # your own tickers (unknown ones get a random seed)
    uv run python demo.py --duration 10      # stop by itself after 10 seconds

Press Ctrl+C to quit.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from app.market import (
    InvalidTickerError,
    MarketDataSource,
    PriceCache,
    create_market_data_source,
    normalize_ticker,
    price_events,
)
from app.market.simulator import SimulatorSource   # only for --fast

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]
SPARK_WIDTH = 30
SPARK_CHARS = "▁▂▃▄▅▆▇█"

# ANSI styles. Brand colors from PLAN.md §2 where the terminal supports 24-bit color.
RESET, BOLD, DIM = "\x1b[0m", "\x1b[1m", "\x1b[2m"
GREEN, RED = "\x1b[32m", "\x1b[31m"
FLASH_UP, FLASH_DOWN = "\x1b[30;42m", "\x1b[30;41m"
YELLOW = "\x1b[38;2;236;173;10m"   # #ecad0a accent
BLUE = "\x1b[38;2;32;157;215m"     # #209dd7 primary
HOME, CLEAR_BELOW = "\x1b[H", "\x1b[J"
HIDE_CURSOR, SHOW_CURSOR, CLEAR_SCREEN = "\x1b[?25l", "\x1b[?25h", "\x1b[2J"


# --- pure helpers (unit-tested in tests/test_demo.py) ---------------------------
def sparkline(values: list[float], width: int = SPARK_WIDTH) -> str:
    """The last `width` values as block characters, scaled to their own min..max."""
    values = values[-width:]
    if not values:
        return ""
    low, high = min(values), max(values)
    if high == low:
        return SPARK_CHARS[3] * len(values)
    top = len(SPARK_CHARS) - 1
    return "".join(SPARK_CHARS[round((v - low) / (high - low) * top)] for v in values)


@dataclass
class Row:
    """What the demo remembers per ticker, following the frontend rules in PLAN.md §10."""

    entry: dict | None = None                         # latest SSE entry
    history: list[float] = field(default_factory=list)
    last_timestamp: str | None = None
    flash: str | None = None                          # "up" / "down" on a price change

    def apply(self, entry: dict, max_points: int = 200) -> None:
        old_price = self.entry["price"] if self.entry else None
        # Flash on a price change versus the last price seen, not on `direction` alone.
        if old_price is not None and entry["price"] != old_price:
            self.flash = "up" if entry["price"] > old_price else "down"
        else:
            self.flash = None
        # Append a chart point only when the timestamp changes.
        if entry["timestamp"] != self.last_timestamp:
            self.history.append(entry["price"])
            del self.history[:-max_points]
            self.last_timestamp = entry["timestamp"]
        self.entry = entry


def render_table(tickers: list[str], rows: dict[str, Row], color: bool = True) -> list[str]:
    """The watchlist as text lines: ticker, price, change %, direction, sparkline."""

    def c(style: str, text: str) -> str:
        return f"{style}{text}{RESET}" if color else text

    lines = [c(BOLD, f"{'TICKER':<7} {'PRICE':>10} {'CHG %':>8}   {'TREND':<{SPARK_WIDTH}}  UPDATED")]
    for ticker in tickers:
        row = rows.get(ticker)
        e = row.entry if row else None
        if e is None:
            lines.append(f"{c(YELLOW, f'{ticker:<7}')} {'—':>10} {'—':>8}   {c(DIM, 'waiting for price data…')}")
            continue
        price = f"{e['price']:>10,.2f}"
        if row.flash == "up":
            price = c(FLASH_UP, price)
        elif row.flash == "down":
            price = c(FLASH_DOWN, price)
        pct = e["change_percent"]
        pct_text = c(GREEN if pct > 0 else RED if pct < 0 else DIM, f"{pct:>+7.2f}%")
        arrow = {"up": c(GREEN, "▲"), "down": c(RED, "▼")}.get(e["direction"], c(DIM, "·"))
        spark = c(BLUE, f"{sparkline(row.history):<{SPARK_WIDTH}}")
        updated = e["timestamp"][11:23]               # HH:MM:SS.mmm (UTC)
        lines.append(f"{c(YELLOW, f'{ticker:<7}')} {price} {pct_text} {arrow} {spark}  {c(DIM, updated)}")
    return lines


def describe_source(source: MarketDataSource) -> str:
    if isinstance(source, SimulatorSource):
        return "Simulator (GBM, 500 ms ticks)"
    return f"Massive API (mode: {getattr(source, 'mode', None) or 'detecting…'})"


# --- live loop -------------------------------------------------------------------
class _Viewer:
    """Stands in for the Starlette Request that price_events() polls for disconnects."""

    def __init__(self, deadline: float | None) -> None:
        self.deadline = deadline

    async def is_disconnected(self) -> bool:
        return self.deadline is not None and time.monotonic() >= self.deadline


def parse_tickers(raw: list[str]) -> tuple[list[str], list[str]]:
    """Normalize like the API does (PLAN.md §6). Returns (valid tickers, skipped inputs)."""
    tickers: list[str] = []
    skipped: list[str] = []
    for item in raw:
        try:
            ticker = normalize_ticker(item)
        except InvalidTickerError:
            skipped.append(item)
            continue
        if ticker not in tickers:
            tickers.append(ticker)
    return tickers, skipped


async def run(tickers: list[str], fast: bool, duration: float | None, skipped: list[str] = ()) -> None:
    cache = PriceCache()
    source = create_market_data_source(cache)
    if fast and isinstance(source, SimulatorSource):
        # time_scale is a code-only knob (design doc §10), so the demo builds its own simulator.
        source = SimulatorSource(cache, time_scale=60)

    started = time.monotonic()
    deadline = started + duration if duration else None
    rows: dict[str, Row] = {}
    events = 0

    await source.start(tickers)
    sys.stdout.write(HIDE_CURSOR + CLEAR_SCREEN)
    try:
        async for event in price_events(cache, _Viewer(deadline)):
            if not event.startswith("data: "):        # the leading "retry:" line
                continue
            events += 1
            for ticker, entry in json.loads(event[len("data: "):]).items():
                rows.setdefault(ticker, Row()).apply(entry)

            speed = "  ·  60x speed" if fast else ""
            header = [
                f"{BOLD}{YELLOW}trading_workstation{RESET}  {DIM}market data demo{RESET}",
                f"Source: {BLUE}{describe_source(source)}{RESET}{speed}",
            ]
            if skipped:
                header.append(f"{RED}Skipped invalid tickers: {', '.join(map(repr, skipped))}{RESET}")
            header.append("")
            footer = [
                "",
                f"{DIM}SSE events: {events}  ·  uptime {time.monotonic() - started:5.1f}s  ·  "
                f"tracking {len(source.tracked_tickers())} tickers  ·  Ctrl+C to quit{RESET}",
            ]
            frame = header + render_table(tickers, rows) + footer
            sys.stdout.write(HOME + "\n".join(line + "\x1b[K" for line in frame) + "\n" + CLEAR_BELOW)
            sys.stdout.flush()
    finally:
        await source.stop()
        sys.stdout.write(SHOW_CURSOR)
        sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="Live terminal demo of the market data backend.")
    parser.add_argument("tickers", nargs="*", help=f"tickers to watch (default: {' '.join(DEFAULT_TICKERS)})")
    parser.add_argument("--fast", action="store_true", help="simulator only: run at 60x market speed")
    parser.add_argument("--duration", type=float, help="stop after this many seconds")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env", override=False)   # same rule as the app (PLAN.md §5)
    if sys.platform == "win32":
        os.system("")                                     # turn on ANSI escape handling in the console
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    tickers, skipped = parse_tickers(args.tickers)
    try:
        asyncio.run(run(tickers or DEFAULT_TICKERS, args.fast, args.duration, skipped))
    except KeyboardInterrupt:
        pass
    print("\nDemo stopped.")


if __name__ == "__main__":
    main()
