import { test, expect } from "@playwright/test";
import {
  gotoApp,
  waitForPrice,
  getPortfolio,
  flatten,
  uiTrade,
  parseMoney,
  errorLocator,
  ensureWatched,
} from "./helpers";

const money = (n: number) => "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const qtyRe = (n: string) => new RegExp(`^\\s*${n.replace(".", "\\.")}(\\.0+)?\\s*$`);

test.describe("trading", () => {
  test("buy shares: cash decreases, position and heatmap cell appear", async ({ page, request }) => {
    const T = "JPM";
    await flatten(request, T);
    const before = await getPortfolio(request);

    await gotoApp(page);
    await waitForPrice(page, T);
    const resp = await uiTrade(page, T, "buy", "3");
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    expect(body.trade).toMatchObject({ ticker: T, side: "buy", quantity: 3 });
    expect(body.trade.price).toBeGreaterThan(0);

    const expectedCash = Math.round((before.cash_balance - 3 * body.trade.price) * 100) / 100;
    expect(body.portfolio.cash_balance).toBeCloseTo(expectedCash, 2);
    await expect(page.getByTestId("header-cash")).toHaveText(money(body.portfolio.cash_balance));

    await expect(page.getByTestId(`position-row-${T}`)).toBeVisible();
    await expect(page.getByTestId(`position-qty-${T}`)).toHaveText(qtyRe("3"));
    await expect(page.getByTestId(`heatmap-cell-${T}`)).toBeVisible();
    await expect(page.getByTestId("positions-empty")).toHaveCount(0);
    await expect(page.getByTestId("heatmap-empty")).toHaveCount(0);

    await flatten(request, T);
  });

  test("sell shares: partial then full exit", async ({ page, request }) => {
    const T = "V";
    await flatten(request, T);
    await gotoApp(page);
    await waitForPrice(page, T);

    expect((await uiTrade(page, T, "buy", "5")).status()).toBe(200);
    await expect(page.getByTestId(`position-qty-${T}`)).toHaveText(qtyRe("5"));
    const cashAfterBuy = (await getPortfolio(request)).cash_balance;

    const partial = await uiTrade(page, T, "sell", "2");
    expect(partial.status()).toBe(200);
    const pBody = await partial.json();
    expect(pBody.portfolio.cash_balance).toBeCloseTo(cashAfterBuy + 2 * pBody.trade.price, 1);
    await expect(page.getByTestId(`position-qty-${T}`)).toHaveText(qtyRe("3"));
    await expect(page.getByTestId("header-cash")).toHaveText(money(pBody.portfolio.cash_balance));

    const full = await uiTrade(page, T, "sell", "3");
    expect(full.status()).toBe(200);
    await expect(page.getByTestId(`position-row-${T}`)).toHaveCount(0);
    await expect(page.getByTestId(`heatmap-cell-${T}`)).toHaveCount(0);
    expect((await getPortfolio(request)).positions.find((p) => p.ticker === T)).toBeUndefined();
  });

  test("fractional quantity is accepted", async ({ page, request }) => {
    const T = "AMZN";
    await flatten(request, T);
    await gotoApp(page);
    await waitForPrice(page, T);
    expect((await uiTrade(page, T, "buy", "0.5")).status()).toBe(200);
    await expect(page.getByTestId(`position-qty-${T}`)).toHaveText(/0?\.5/);
    await flatten(request, T);
  });

  test("insufficient cash shows the API error", async ({ page, request }) => {
    const T = "NVDA";
    await gotoApp(page);
    await waitForPrice(page, T);
    const cashBefore = (await getPortfolio(request)).cash_balance;
    const resp = await uiTrade(page, T, "buy", "1000000");
    expect(resp.status()).toBe(400);
    expect((await resp.json()).detail).toMatch(/^Insufficient cash: need \$[\d,]+\.\d{2}, have \$[\d,]+\.\d{2}$/);
    await expect(errorLocator(page).filter({ hasText: /Insufficient cash/ }).first()).toBeVisible();
    expect((await getPortfolio(request)).cash_balance).toBe(cashBefore);
  });

  test("selling more than held shows the API error", async ({ page, request }) => {
    const T = "GOOGL";
    await flatten(request, T);
    await gotoApp(page);
    await waitForPrice(page, T);
    const resp = await uiTrade(page, T, "sell", "1");
    expect(resp.status()).toBe(400);
    await expect(errorLocator(page).filter({ hasText: /Insufficient shares/ }).first()).toBeVisible();
  });

  test("buying an unwatched ticker auto-adds it to the watchlist", async ({ page, request }) => {
    const T = "ORCL";
    await flatten(request, T);
    await request.delete(`/api/watchlist/${T}`);
    await gotoApp(page);
    await expect(page.getByTestId(`watchlist-row-${T}`)).toHaveCount(0);

    expect((await uiTrade(page, T, "buy", "1")).status()).toBe(200);
    await expect(page.getByTestId(`watchlist-row-${T}`)).toBeVisible();
    await expect(page.getByTestId(`position-row-${T}`)).toBeVisible();

    await flatten(request, T);
    await request.delete(`/api/watchlist/${T}`);
  });

  test("header total tracks cash + live position value", async ({ page, request }) => {
    const T = "MSFT";
    await flatten(request, T);
    await ensureWatched(request, T);
    await gotoApp(page);
    await waitForPrice(page, T);
    expect((await uiTrade(page, T, "buy", "2")).status()).toBe(200);
    await expect(page.getByTestId(`position-row-${T}`)).toBeVisible();

    // Header total is computed on the frontend from live prices; it should agree with the API within drift.
    await expect
      .poll(
        async () => {
          const p = await getPortfolio(request);
          const total = parseMoney(await page.getByTestId("header-total-value").textContent());
          return Math.abs(total - p.total_value) / p.total_value;
        },
        { timeout: 10_000 },
      )
      .toBeLessThan(0.005);
    await flatten(request, T);
  });
});
