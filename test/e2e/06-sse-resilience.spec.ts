import { test, expect } from "@playwright/test";
import { gotoApp, waitConnected } from "./helpers";

const STREAM = "**/api/stream/prices";

test.describe("SSE resilience", () => {
  test.beforeEach(async ({ page }) => {
    // Record every EventSource the app creates so a test can drop live connections.
    await page.addInitScript(() => {
      const Orig = window.EventSource;
      const list: EventSource[] = [];
      (window as any).__eventSources = list;
      class Tracked extends Orig {
        constructor(url: string | URL, init?: EventSourceInit) {
          super(url, init);
          list.push(this);
        }
      }
      (window as any).EventSource = Tracked;
    });
  });

  test("dropped stream goes non-green, then reconnects", async ({ page }) => {
    await gotoApp(page);
    await waitConnected(page);
    const dot = page.getByTestId("connection-status");

    // Block new stream connections, then kill the live one.
    await page.route(STREAM, (route) => route.abort("connectionreset"));
    await page.evaluate(() => (window as any).__eventSources.forEach((es: EventSource) => es.close()));

    await expect(dot).not.toHaveAttribute("data-status", "connected", { timeout: 8_000 });
    await expect(dot).toHaveAttribute("data-status", /reconnecting|disconnected/);

    // Allow connections again: the app (or EventSource retry) must recover on its own.
    await page.unroute(STREAM);
    await waitConnected(page, 25_000);

    // And prices keep flowing afterwards.
    const price = page.getByTestId("price-AAPL");
    const before = await price.textContent();
    await expect.poll(() => price.textContent(), { timeout: 10_000 }).not.toBe(before);
  });

  test("stale stream (no events for >5s) shows reconnecting", async ({ page }) => {
    // Serve a stream that opens but never sends data.
    await page.route(STREAM, (route) =>
      route.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" },
        body: ": keepalive\n\n",
      }),
    );
    await gotoApp(page);
    await expect(page.getByTestId("connection-status")).not.toHaveAttribute("data-status", "connected", {
      timeout: 3_000,
    });
    await page.unroute(STREAM);
    await waitConnected(page, 25_000);
  });

  test("going offline and back online recovers", async ({ page, context }) => {
    await gotoApp(page);
    await waitConnected(page);
    await context.setOffline(true);
    await page.evaluate(() => (window as any).__eventSources.forEach((es: EventSource) => es.close()));
    await expect(page.getByTestId("connection-status")).not.toHaveAttribute("data-status", "connected", {
      timeout: 8_000,
    });
    await context.setOffline(false);
    await waitConnected(page, 25_000);
  });
});
