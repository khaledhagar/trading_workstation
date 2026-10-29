import { test, expect } from "@playwright/test";
import { DEFAULT_TICKERS, gotoApp, waitConnected, waitForPrice, getPortfolio, parseMoney } from "./helpers";

// Runs first (file order) against a fresh database: local runs use a temp DB_PATH,
// Docker runs use a fresh container volume.
test.describe("fresh start", () => {
  test("default watchlist, $10k cash, prices streaming", async ({ page, request }) => {
    const portfolio = await getPortfolio(request);
    expect(portfolio.cash_balance).toBe(10000);
    expect(portfolio.positions).toEqual([]);
    expect(portfolio.total_value).toBe(10000);

    await gotoApp(page);

    for (const t of DEFAULT_TICKERS) {
      await expect(page.getByTestId(`watchlist-row-${t}`)).toBeVisible();
    }
    await expect(page.getByTestId("header-cash")).toHaveText(/\$10,000\.00/);
    await expect(page.getByTestId("header-total-value")).toHaveText(/\$10,000\.00/);

    await waitConnected(page);
    for (const t of DEFAULT_TICKERS) await waitForPrice(page, t);

    // Prices actually change over time (simulator ticks every ~500ms).
    const readAll = () => Promise.all(DEFAULT_TICKERS.map((t) => page.getByTestId(`price-${t}`).textContent()));
    const first = (await readAll()).join("|");
    await expect.poll(async () => (await readAll()).join("|"), { timeout: 10_000 }).not.toBe(first);

    for (const t of DEFAULT_TICKERS) {
      await expect(page.getByTestId(`change-${t}`)).toHaveText(/\d/);
    }
  });

  test("empty states for a fresh portfolio", async ({ page }) => {
    await gotoApp(page);
    await expect(page.getByTestId("heatmap-empty")).toBeVisible();
    await expect(page.getByTestId("positions-empty")).toBeVisible();
    // Main chart auto-selects the first watchlist ticker.
    await expect(page.getByTestId("main-chart-ticker")).toHaveText(/AAPL/);
  });

  test("sparklines and main chart fill in from the stream", async ({ page }) => {
    await gotoApp(page);
    await waitConnected(page);
    const spark = page.getByTestId("sparkline-AAPL");
    await expect(spark).toBeVisible();
    await expect
      .poll(
        async () => {
          const pts = await spark.locator("polyline").first().getAttribute("points").catch(() => null);
          return pts ? pts.trim().split(/\s+/).length : 0;
        },
        { timeout: 10_000 },
      )
      .toBeGreaterThanOrEqual(2);

    await page.getByTestId("watchlist-row-MSFT").click();
    await expect(page.getByTestId("main-chart-ticker")).toHaveText(/MSFT/);
    await expect(page.getByTestId("main-chart").locator("canvas").first()).toBeVisible({ timeout: 10_000 });
  });

  test("header total equals cash when there are no positions", async ({ page }) => {
    await gotoApp(page);
    const cash = parseMoney(await page.getByTestId("header-cash").textContent());
    const total = parseMoney(await page.getByTestId("header-total-value").textContent());
    expect(total).toBeCloseTo(cash, 2);
  });
});
