"""The terminal demo (demo.py): its pure helpers and one short end-to-end run."""

import demo
from demo import SPARK_CHARS, Row, parse_tickers, render_table, sparkline


def entry(price: float, ts: str = "2026-01-01T12:00:00.000Z", direction: str = "flat", pct: float = 0.0) -> dict:
    return {"ticker": "AAPL", "price": price, "previous_price": price, "timestamp": ts,
            "direction": direction, "change_percent": pct}


def test_sparkline_scales_to_min_max():
    assert sparkline([]) == ""
    assert sparkline([1.0, 2.0, 3.0]) == SPARK_CHARS[0] + SPARK_CHARS[4] + SPARK_CHARS[-1]
    assert sparkline([5.0, 5.0]) == SPARK_CHARS[3] * 2          # flat line, no divide by zero


def test_sparkline_keeps_only_the_last_width_values():
    assert len(sparkline(list(range(100)), width=10)) == 10


def test_row_flashes_on_price_change_only():
    row = Row()
    row.apply(entry(190.0))
    assert row.flash is None                                    # first price: nothing to compare
    row.apply(entry(190.5, "2026-01-01T12:00:00.500Z", "up"))
    assert row.flash == "up"
    row.apply(entry(190.5, "2026-01-01T12:00:01.000Z", "up"))   # same price, stale "up"
    assert row.flash is None
    row.apply(entry(190.1, "2026-01-01T12:00:01.500Z", "down"))
    assert row.flash == "down"


def test_row_appends_history_only_on_new_timestamp():
    row = Row()
    for _ in range(3):
        row.apply(entry(190.0))                                 # Massive re-sends the same entry
    assert row.history == [190.0]
    row.apply(entry(191.0, "2026-01-01T12:00:15.000Z"))
    assert row.history == [190.0, 191.0]


def test_row_history_is_capped():
    row = Row()
    for i in range(50):
        row.apply(entry(100.0 + i, f"t{i}"), max_points=10)
    assert len(row.history) == 10 and row.history[-1] == 149.0


def test_parse_tickers_normalizes_dedupes_and_reports_invalid():
    assert parse_tickers([" pypl ", "brk.b", "PYPL", "12AB", ""]) == (["PYPL", "BRK.B"], ["12AB", ""])
    assert parse_tickers([]) == ([], [])


def test_render_table_without_color():
    rows = {"AAPL": Row()}
    rows["AAPL"].apply(entry(190.0))
    rows["AAPL"].apply(entry(191.9, "2026-01-01T12:00:00.500Z", "up", 1.0))
    lines = render_table(["AAPL", "MSFT"], rows, color=False)
    assert lines[0].split()[:3] == ["TICKER", "PRICE", "CHG"]
    assert "191.90" in lines[1] and "+1.00%" in lines[1] and "▲" in lines[1] and "12:00:00.500" in lines[1]
    assert "MSFT" in lines[2] and "waiting for price data" in lines[2]
    assert all("\x1b" not in line for line in lines)


async def test_end_to_end_short_run(capsys, monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)        # always the simulator
    await demo.run(["AAPL", "ZZZ"], fast=True, duration=1.2, skipped=["12AB"])
    out = capsys.readouterr().out
    assert "Simulator" in out and "60x speed" in out
    assert "AAPL" in out and "ZZZ" in out
    assert "Skipped invalid tickers: '12AB'" in out
    assert "SSE events: 2" in out                               # events actually flowed
    assert out.endswith(demo.SHOW_CURSOR)                       # cursor restored on exit
