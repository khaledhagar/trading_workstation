import { expect, test, type Page } from "@playwright/test";

const DEFAULT_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"];

const money = (text: string | null) => Number((text ?? "").replace(/[$,]/g, ""));

async function cash(page: Page) {
  return money(await page.getByTestId("cash-balance").textContent());
}

async function trade(page: Page, ticker: string, qty: string, side: "buy" | "sell") {
  await page.getByTestId("trade-ticker").fill(ticker);
  await page.getByTestId("trade-qty").fill(qty);
  await page.getByTestId(`${side}-button`).click();
  await expect(page.getByTestId("trade-result")).toBeVisible();
}

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("connection-status")).toHaveAttribute("data-status", "connected");
});

test("fresh start: default watchlist, $10k cash, streaming prices", async ({ page }) => {
  for (const t of DEFAULT_TICKERS) {
    await expect(page.getByTestId(`watch-row-${t}`)).toBeVisible();
  }
  const total = money(await page.getByTestId("total-value").textContent());
  expect(total).toBeGreaterThan(0);

  // Prices change over time (the simulator ticks every 500 ms).
  const read = () =>
    Promise.all(DEFAULT_TICKERS.map((t) => page.getByTestId(`price-${t}`).textContent()));
  const before = await read();
  await expect.poll(async () => (await read()).join() !== before.join(), { timeout: 15_000 }).toBe(true);
  await expect(page.getByTestId("sparkline").first()).toBeVisible();
  await expect(page.getByTestId("main-chart").locator("canvas").first()).toBeVisible();
});

test("add and remove a ticker from the watchlist", async ({ page }) => {
  await page.getByTestId("watch-input").fill("pypl");
  await page.getByTestId("watch-add").click();
  await expect(page.getByTestId("watch-row-PYPL")).toBeVisible();
  await expect(page.getByTestId("price-PYPL")).not.toHaveText("—");

  await page.getByTestId("watch-input").fill("12AB");
  await page.getByTestId("watch-add").click();
  await expect(page.getByTestId("watch-error")).toHaveText("Invalid ticker");

  await page.getByTestId("watch-row-PYPL").hover();
  await page.getByTestId("remove-PYPL").click();
  await expect(page.getByTestId("watch-row-PYPL")).toHaveCount(0);
});

test("buy then sell shares", async ({ page }) => {
  const startCash = await cash(page);
  await trade(page, "AMZN", "3", "buy");
  await expect(page.getByTestId("trade-result")).toContainText("Bought 3 AMZN");
  await expect(page.getByTestId("position-AMZN")).toBeVisible();
  await expect.poll(() => cash(page)).toBeLessThan(startCash);
  const afterBuy = await cash(page);

  await trade(page, "AMZN", "1", "sell");
  await expect(page.getByTestId("position-qty-AMZN")).toHaveText("2");
  await expect.poll(() => cash(page)).toBeGreaterThan(afterBuy);

  await trade(page, "AMZN", "2", "sell");
  await expect(page.getByTestId("position-AMZN")).toHaveCount(0);

  await trade(page, "AMZN", "1", "sell");
  await expect(page.getByTestId("trade-result")).toContainText("Insufficient shares");
});

test("portfolio visualizations: heatmap and P&L chart", async ({ page }) => {
  await trade(page, "META", "2", "buy");
  const cell = page.getByTestId("heat-META");
  await expect(cell).toBeVisible();
  const fill = await cell.locator("rect").getAttribute("fill");
  expect(fill).toMatch(/^rgb\(\d+, \d+, \d+\)$/);
  // Color follows the ±5% scale: green channel dominates on gains, red on losses.
  const pnl = Number(await cell.getAttribute("data-pnl"));
  const [r, g] = fill!.match(/\d+/g)!.map(Number);
  if (pnl > 0.5) expect(g).toBeGreaterThan(r);
  if (pnl < -0.5) expect(r).toBeGreaterThan(g);

  // Startup snapshot + post-trade snapshot → the chart renders.
  await expect(page.getByTestId("pnl-chart").locator("canvas").first()).toBeVisible();
  await trade(page, "META", "2", "sell");
});

test("AI chat (mocked): trade executes and shows inline", async ({ page }) => {
  await page.getByTestId("chat-input").fill("Please buy 2 NVDA");
  await page.getByTestId("chat-send").click();
  const reply = page.getByTestId("chat-assistant").last();
  await expect(reply).toContainText("Buying 2 NVDA.");
  await expect(reply.getByTestId("chat-action")).toHaveAttribute("data-status", "executed");
  await expect(page.getByTestId("position-NVDA")).toBeVisible();

  await page.getByTestId("chat-input").fill("sell 50 NVDA");
  await page.getByTestId("chat-send").click();
  const failed = page.getByTestId("chat-assistant").last();
  await expect(failed.getByTestId("chat-action")).toHaveAttribute("data-status", "failed");
  await expect(failed).toContainText("Insufficient shares");

  // History survives a reload.
  await page.reload();
  await expect(page.getByTestId("chat-assistant").filter({ hasText: "Buying 2 NVDA." })).toBeVisible();
  await page.getByTestId("chat-input").fill("sell 2 NVDA");
  await page.getByTestId("chat-send").click();
  await expect(page.getByTestId("position-NVDA")).toHaveCount(0);
});

test("SSE resilience: reconnects after the stream drops", async ({ page }) => {
  // Make the stream endpoint unreachable: the indicator must leave "connected".
  await page.route("**/api/stream/prices", (route) => route.abort("connectionreset"));
  await page.reload();
  await expect(page.getByTestId("connection-status")).not.toHaveAttribute("data-status", "connected");
  await page.waitForTimeout(2_000);
  await expect(page.getByTestId("connection-status")).not.toHaveAttribute("data-status", "connected");

  // Restore it: the client retries on its own and goes green again.
  await page.unroute("**/api/stream/prices");
  await expect(page.getByTestId("connection-status")).toHaveAttribute("data-status", "connected", {
    timeout: 20_000,
  });
});
