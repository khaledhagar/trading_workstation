import { APIRequestContext, Page, expect, Locator } from "@playwright/test";

export const DEFAULT_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"];

export type Position = {
  ticker: string;
  quantity: number;
  avg_cost: number;
  current_price: number;
  market_value: number;
  unrealized_pnl: number;
  pnl_percent: number;
};
export type Portfolio = {
  cash_balance: number;
  positions_value: number;
  total_value: number;
  unrealized_pnl: number;
  positions: Position[];
};

/** "$10,000.00" / "-$3.80" / "10,000.00" -> number */
export function parseMoney(text: string | null): number {
  if (!text) return NaN;
  const neg = /-|−|\(/.test(text);
  const n = parseFloat(text.replace(/[^0-9.]/g, ""));
  return neg ? -n : n;
}

export async function getPortfolio(request: APIRequestContext): Promise<Portfolio> {
  const res = await request.get("/api/portfolio");
  expect(res.status()).toBe(200);
  return res.json();
}

export async function getWatchlist(request: APIRequestContext): Promise<any[]> {
  const res = await request.get("/api/watchlist");
  expect(res.status()).toBe(200);
  return res.json();
}

export async function apiTrade(request: APIRequestContext, ticker: string, side: "buy" | "sell", quantity: number) {
  return request.post("/api/portfolio/trade", { data: { ticker, side, quantity } });
}

/** Sell any holding of `ticker` so the test starts flat. */
export async function flatten(request: APIRequestContext, ticker: string) {
  const p = await getPortfolio(request);
  const pos = p.positions.find((x) => x.ticker === ticker);
  if (pos && pos.quantity > 0) {
    const res = await apiTrade(request, ticker, "sell", pos.quantity);
    expect(res.status(), await res.text()).toBe(200);
  }
}

export async function ensureWatched(request: APIRequestContext, ticker: string) {
  const res = await request.post("/api/watchlist", { data: { ticker } });
  expect(res.status(), await res.text()).toBe(200);
}

export async function ensureUnwatched(request: APIRequestContext, ticker: string) {
  const res = await request.delete(`/api/watchlist/${ticker}`);
  expect([200, 404]).toContain(res.status());
}

/** Wait until a ticker has a live price rendered in the watchlist. */
export async function waitForPrice(page: Page, ticker: string) {
  await expect(page.getByTestId(`price-${ticker}`)).toHaveText(/\d/, { timeout: 15_000 });
}

export async function gotoApp(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("watchlist")).toBeVisible();
}

export async function waitConnected(page: Page, timeout = 15_000) {
  await expect(page.getByTestId("connection-status")).toHaveAttribute("data-status", "connected", { timeout });
}

export async function openChat(page: Page): Promise<Locator> {
  const input = page.getByTestId("chat-input");
  if (!(await input.isVisible())) {
    await page.getByTestId("chat-toggle").click();
  }
  await expect(input).toBeVisible();
  return input;
}

/** Send a chat message through the UI and wait for the POST /api/chat response. */
export async function sendChat(page: Page, text: string) {
  const input = await openChat(page);
  const assistantBefore = await page.getByTestId("chat-message-assistant").count();
  await input.fill(text);
  const respP = page.waitForResponse((r) => r.url().endsWith("/api/chat") && r.request().method() === "POST");
  await page.getByTestId("chat-send").click();
  const resp = await respP;
  expect(resp.status()).toBe(200);
  await expect(page.getByTestId("chat-message-assistant")).toHaveCount(assistantBefore + 1);
  return resp.json();
}

/** Trade via the trade bar; returns the HTTP response. */
export async function uiTrade(page: Page, ticker: string, side: "buy" | "sell", quantity: string) {
  await page.getByTestId("trade-ticker").fill(ticker);
  await page.getByTestId("trade-quantity").fill(quantity);
  const respP = page.waitForResponse((r) => r.url().includes("/api/portfolio/trade"));
  await page.getByTestId(side === "buy" ? "trade-buy" : "trade-sell").click();
  return respP;
}

/** Any displayed API error (toast or inline trade error). */
export function errorLocator(page: Page): Locator {
  return page.locator('[data-testid="toast"], [data-testid="error-message"], [data-testid="trade-error"]');
}
