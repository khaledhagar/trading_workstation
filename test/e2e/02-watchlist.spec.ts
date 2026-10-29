import { test, expect } from "@playwright/test";
import { gotoApp, waitForPrice, getWatchlist, ensureUnwatched, errorLocator } from "./helpers";

test.describe("watchlist", () => {
  test("add and remove a ticker through the UI", async ({ page, request }) => {
    const T = "PYPL";
    await ensureUnwatched(request, T);
    await gotoApp(page);
    await expect(page.getByTestId(`watchlist-row-${T}`)).toHaveCount(0);

    await page.getByTestId("watchlist-add-input").fill(" pypl ");
    await page.getByTestId("watchlist-add-button").click();
    await expect(page.getByTestId(`watchlist-row-${T}`)).toBeVisible();
    await waitForPrice(page, T);
    expect((await getWatchlist(request)).map((r) => r.ticker)).toContain(T);

    // Persisted across reload.
    await page.reload();
    await expect(page.getByTestId(`watchlist-row-${T}`)).toBeVisible();

    await page.getByTestId(`remove-${T}`).click();
    await expect(page.getByTestId(`watchlist-row-${T}`)).toHaveCount(0);
    expect((await getWatchlist(request)).map((r) => r.ticker)).not.toContain(T);
  });

  test("invalid ticker shows an error and adds nothing", async ({ page, request }) => {
    await gotoApp(page);
    const before = (await getWatchlist(request)).length;
    await page.getByTestId("watchlist-add-input").fill("12-X");
    await page.getByTestId("watchlist-add-button").click();
    await expect(errorLocator(page).filter({ hasText: /Invalid ticker/i }).first()).toBeVisible();
    expect((await getWatchlist(request)).length).toBe(before);
  });
});
