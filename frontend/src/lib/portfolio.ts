import type { Portfolio, PriceUpdate } from "./types";

export type PriceMap = Record<string, PriceUpdate | undefined>;

/** Live price for a position: the latest SSE price, else the portfolio response's current_price. */
export function livePrice(ticker: string, fallback: number, prices: PriceMap): number {
  const p = prices[ticker]?.price;
  return typeof p === "number" && Number.isFinite(p) ? p : fallback;
}

/** cash + Σ(quantity × latest SSE price), falling back to current_price until an SSE price arrives. */
export function computeTotalValue(
  portfolio: Pick<Portfolio, "cash_balance" | "positions"> | null,
  prices: PriceMap,
): number | null {
  if (!portfolio) return null;
  const positionsValue = portfolio.positions.reduce(
    (sum, pos) => sum + pos.quantity * livePrice(pos.ticker, pos.current_price, prices),
    0,
  );
  return Math.round((portfolio.cash_balance + positionsValue) * 100) / 100;
}

/** Position values re-marked to the latest SSE price. */
export function livePosition(pos: Portfolio["positions"][number], prices: PriceMap) {
  const price = livePrice(pos.ticker, pos.current_price, prices);
  const marketValue = pos.quantity * price;
  const cost = pos.quantity * pos.avg_cost;
  const pnl = marketValue - cost;
  const pnlPercent = cost > 0 ? (pnl / cost) * 100 : 0;
  return { ...pos, current_price: price, market_value: marketValue, unrealized_pnl: pnl, pnl_percent: pnlPercent };
}
