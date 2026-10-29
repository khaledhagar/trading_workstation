import { describe, expect, it } from "vitest";
import { computeTotalValue, livePosition } from "./portfolio";
import type { Position, PriceUpdate } from "./types";

function pos(ticker: string, quantity: number, avg_cost: number, current_price: number): Position {
  return {
    ticker,
    quantity,
    avg_cost,
    current_price,
    market_value: quantity * current_price,
    unrealized_pnl: quantity * (current_price - avg_cost),
    pnl_percent: 0,
  };
}

function price(ticker: string, p: number): PriceUpdate {
  return { ticker, price: p, previous_price: p, timestamp: "2026-01-01T12:00:00.000Z", direction: "flat", change_percent: 0 };
}

describe("computeTotalValue", () => {
  it("returns null before the portfolio loads", () => {
    expect(computeTotalValue(null, {})).toBeNull();
  });

  it("is just cash with no positions", () => {
    expect(computeTotalValue({ cash_balance: 10000, positions: [] }, {})).toBe(10000);
  });

  it("uses live SSE prices for positions", () => {
    const portfolio = { cash_balance: 8098.8, positions: [pos("AAPL", 10, 190.12, 190.5)] };
    expect(computeTotalValue(portfolio, { AAPL: price("AAPL", 192) })).toBe(10018.8);
  });

  it("falls back to current_price until an SSE price arrives", () => {
    const portfolio = {
      cash_balance: 1000,
      positions: [pos("AAPL", 10, 190, 190.5), pos("MSFT", 2, 400, 410)],
    };
    // AAPL live, MSFT fallback
    expect(computeTotalValue(portfolio, { AAPL: price("AAPL", 200) })).toBe(1000 + 2000 + 820);
  });

  it("handles fractional quantities and rounds to cents", () => {
    const portfolio = { cash_balance: 0.1, positions: [pos("TSLA", 0.3333, 250, 250)] };
    expect(computeTotalValue(portfolio, { TSLA: price("TSLA", 251.37) })).toBe(83.88);
  });
});

describe("livePosition", () => {
  it("re-marks value and P&L to the live price", () => {
    const p = livePosition(pos("AAPL", 10, 100, 100), { AAPL: price("AAPL", 105) });
    expect(p.current_price).toBe(105);
    expect(p.market_value).toBe(1050);
    expect(p.unrealized_pnl).toBe(50);
    expect(p.pnl_percent).toBeCloseTo(5);
  });
});
