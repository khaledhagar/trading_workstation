import { test, expect } from "@playwright/test";
import { gotoApp, waitForPrice, getPortfolio, flatten, apiTrade, ensureWatched } from "./helpers";

/** Parse "rgb(a, b, c)" / "#rrggbb" into [r, g, b]. */
function parseColor(c: string): [number, number, number] | null {
  const m = c.match(/rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)/);
  if (m) return [+m[1], +m[2], +m[3]];
  const h = c.match(/^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})/i);
  if (h) return [parseInt(h[1], 16), parseInt(h[2], 16), parseInt(h[3], 16)];
  return null;
}

test.describe("portfolio visualization", () => {
  const TICKERS = ["META", "NFLX"];

  test.beforeEach(async ({ request }) => {
    for (const t of TICKERS) {
      await ensureWatched(request, t);
      await flatten(request, t);
    }
  });
  test.afterEach(async ({ request }) => {
    for (const t of TICKERS) await flatten(request, t);
  });

  test("heatmap cells carry P&L and are coloured by sign", async ({ page, request }) => {
    for (const [t, q] of [["META", 2], ["NFLX", 1]] as const) {
      const r = await apiTrade(request, t, "buy", q);
      expect(r.status(), await r.text()).toBe(200);
    }
    await gotoApp(page);
    await waitForPrice(page, "META");

    for (const t of TICKERS) {
      const cell = page.getByTestId(`heatmap-cell-${t}`);
      await expect(cell).toBeVisible();
      await expect(cell).toHaveAttribute("data-pnl-percent", /^-?\d+(\.\d+)?$/);

      const attr = parseFloat((await cell.getAttribute("data-pnl-percent"))!);
      const pos = (await getPortfolio(request)).positions.find((p) => p.ticker === t)!;
      // Same quantity as the API, allowing for live price drift since the read.
      expect(Math.abs(attr - pos.pnl_percent)).toBeLessThan(2);

      // Colour sanity: only meaningful when P&L is clearly away from 0.
      if (Math.abs(attr) >= 0.5) {
        const fill = await cell.evaluate((el) => {
          const shape = el.matches("rect,path") ? el : el.querySelector("rect,path") || el;
          const cs = getComputedStyle(shape as Element);
          return (shape as Element).getAttribute("fill") || cs.fill || cs.backgroundColor;
        });
        const rgb = parseColor(fill || "");
        if (rgb) {
          if (attr > 0) expect(rgb[1]).toBeGreaterThan(rgb[0]);
          else expect(rgb[0]).toBeGreaterThan(rgb[1]);
        }
      }
    }
    // Larger position (by market value) gets a larger rectangle.
    const p = await getPortfolio(request);
    const mv = Object.fromEntries(p.positions.map((x) => [x.ticker, x.market_value]));
    const area = async (t: string) => {
      const b = await page.getByTestId(`heatmap-cell-${t}`).boundingBox();
      return b ? b.width * b.height : 0;
    };
    const [big, small] = mv.META >= mv.NFLX ? ["META", "NFLX"] : ["NFLX", "META"];
    expect(await area(big)).toBeGreaterThan(await area(small));
  });

  test("P&L chart renders once there are snapshots", async ({ page, request }) => {
    // Each trade records a snapshot; startup recorded one too.
    expect((await apiTrade(request, "META", "buy", 1)).status()).toBe(200);
    const hist = await (await request.get("/api/portfolio/history")).json();
    expect(Array.isArray(hist)).toBe(true);
    expect(hist.length).toBeGreaterThanOrEqual(2);
    expect(hist[0]).toEqual({ total_value: expect.any(Number), recorded_at: expect.any(String) });
    expect(Date.parse(hist[hist.length - 1].recorded_at)).toBeGreaterThanOrEqual(Date.parse(hist[0].recorded_at));

    await gotoApp(page);
    await expect(page.getByTestId("pnl-chart")).toBeVisible();
    await expect(page.getByTestId("pnl-chart-empty")).toHaveCount(0);
    await expect(page.getByTestId("pnl-chart").locator("canvas").first()).toBeVisible();
  });

  test("positions table shows each holding", async ({ page, request }) => {
    expect((await apiTrade(request, "NFLX", "buy", 1.25)).status()).toBe(200);
    await gotoApp(page);
    await expect(page.getByTestId("positions-table")).toBeVisible();
    await expect(page.getByTestId("position-row-NFLX")).toBeVisible();
    await expect(page.getByTestId("position-qty-NFLX")).toHaveText(/1\.25/);
    await expect(page.getByTestId("position-pnl-NFLX")).toHaveText(/\d/);
  });
});
