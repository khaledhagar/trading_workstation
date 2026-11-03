import type { Portfolio, PriceTick } from "./types";

/** cash + Σ(quantity × latest SSE price), falling back to the position's current_price. */
export function liveTotalValue(
  portfolio: Portfolio | null,
  prices: Record<string, PriceTick>,
): number | null {
  if (!portfolio) return null;
  let total = portfolio.cash_balance;
  for (const p of portfolio.positions) {
    const live = prices[p.ticker]?.price;
    total += p.quantity * (typeof live === "number" ? live : p.current_price);
  }
  return Math.round(total * 100) / 100;
}

/** Positions re-valued at live prices (for the table and heatmap). */
export function livePositions(portfolio: Portfolio | null, prices: Record<string, PriceTick>) {
  if (!portfolio) return [];
  return portfolio.positions.map((p) => {
    const price = prices[p.ticker]?.price ?? p.current_price;
    const marketValue = p.quantity * price;
    const cost = p.quantity * p.avg_cost;
    const pnl = marketValue - cost;
    return {
      ...p,
      current_price: price,
      market_value: marketValue,
      unrealized_pnl: pnl,
      pnl_percent: cost > 0 ? (pnl / cost) * 100 : 0,
    };
  });
}
