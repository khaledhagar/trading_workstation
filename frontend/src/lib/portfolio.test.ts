import { heatColor, heatLimit } from "./heatmap";
import { livePositions, liveTotalValue } from "./portfolio";
import type { Portfolio, PriceTick } from "./types";

const portfolio: Portfolio = {
  cash_balance: 1000,
  positions_value: 0,
  total_value: 0,
  unrealized_pnl: 0,
  positions: [
    { ticker: "AAPL", quantity: 10, avg_cost: 100, current_price: 110, market_value: 1100, unrealized_pnl: 100, pnl_percent: 10 },
    { ticker: "MSFT", quantity: 2, avg_cost: 50, current_price: 40, market_value: 80, unrealized_pnl: -20, pnl_percent: -20 },
  ],
};

const tick = (ticker: string, price: number) =>
  ({ ticker, price, previous_price: price, timestamp: "", direction: "flat", change_percent: 0 }) as PriceTick;

describe("liveTotalValue", () => {
  it("uses SSE prices and falls back to current_price", () => {
    expect(liveTotalValue(portfolio, { AAPL: tick("AAPL", 120) })).toBe(1000 + 1200 + 80);
    expect(liveTotalValue(portfolio, {})).toBe(1000 + 1100 + 80);
    expect(liveTotalValue(null, {})).toBeNull();
  });

  it("re-values positions live", () => {
    const [aapl] = livePositions(portfolio, { AAPL: tick("AAPL", 90) });
    expect(aapl.market_value).toBe(900);
    expect(aapl.unrealized_pnl).toBe(-100);
    expect(aapl.pnl_percent).toBeCloseTo(-10);
  });
});

describe("heatLimit", () => {
  it("follows the largest move, clamped to [0.5%, 5%]", () => {
    expect(heatLimit([0.1, -0.2])).toBe(0.5);
    expect(heatLimit([1.2, -3])).toBe(3);
    expect(heatLimit([12])).toBe(5);
    expect(heatLimit([])).toBe(0.5);
    expect(heatLimit([Number.NaN])).toBe(0.5);
  });
});

describe("heatColor", () => {
  it("is neutral gray at 0 and fully saturated at the limit", () => {
    expect(heatColor(0)).toBe("rgb(55, 62, 72)");
    expect(heatColor(0.001)).toBe("rgb(55, 62, 72)");
    expect(heatColor(5)).toBe("rgb(22, 163, 74)");
    expect(heatColor(12)).toBe("rgb(22, 163, 74)");
    expect(heatColor(-5)).toBe("rgb(220, 38, 38)");
    expect(heatColor(0.5, 0.5)).toBe("rgb(22, 163, 74)");
    expect(heatColor(Number.NaN)).toBe("rgb(55, 62, 72)");
  });

  it("gives small moves a visible minimum tint", () => {
    // 0.01% on a ±0.5% scale: t = 0.35 + 0.65 × 0.02 = 0.363
    expect(heatColor(0.01, 0.5)).toBe("rgb(43, 99, 73)");
    expect(heatColor(-0.01, 0.5)).toBe("rgb(115, 53, 60)");
  });

  it("scales linearly above the minimum tint", () => {
    // half the limit: t = 0.35 + 0.65 × 0.5 = 0.675
    expect(heatColor(2.5)).toBe("rgb(33, 130, 73)");
    expect(heatColor(-2.5)).toBe("rgb(166, 46, 49)");
  });
});
