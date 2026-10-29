import { test, expect } from "@playwright/test";
import { apiTrade, flatten, getWatchlist, ensureWatched } from "./helpers";

const ISO_Z = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/;

// API-level contract checks (PLAN.md §8), run through the same origin as the UI.
test.describe("API contract", () => {
  test("health", async ({ request }) => {
    const r = await request.get("/api/health");
    expect(r.status()).toBe(200);
    expect(await r.json()).toEqual({ status: "ok" });
  });

  test("static frontend served at /", async ({ request }) => {
    const r = await request.get("/");
    expect(r.status()).toBe(200);
    expect(r.headers()["content-type"]).toContain("text/html");
  });

  test("watchlist row shape", async ({ request }) => {
    const rows = await getWatchlist(request);
    expect(rows.length).toBeGreaterThan(0);
    for (const r of rows) {
      expect(Object.keys(r).sort()).toEqual(
        ["change_percent", "direction", "previous_price", "price", "ticker", "timestamp"].sort(),
      );
      if (r.price !== null) {
        expect(["up", "down", "flat"]).toContain(r.direction);
        expect(r.timestamp).toMatch(ISO_Z);
      }
    }
  });

  test("watchlist add is idempotent and normalizes; delete 404 when absent", async ({ request }) => {
    const T = "DIS";
    await request.delete(`/api/watchlist/${T}`);
    const a1 = await request.post("/api/watchlist", { data: { ticker: "  dis " } });
    expect(a1.status()).toBe(200);
    const a2 = await request.post("/api/watchlist", { data: { ticker: "DIS" } });
    expect(a2.status()).toBe(200);
    const rows: any[] = await a2.json();
    expect(rows.filter((r) => r.ticker === T)).toHaveLength(1);
    // Seeded immediately -> has a price.
    expect(rows.find((r) => r.ticker === T).price).toBeGreaterThan(0);

    const d1 = await request.delete(`/api/watchlist/${T}`);
    expect(d1.status()).toBe(200);
    expect((await d1.json()).map((r: any) => r.ticker)).not.toContain(T);
    const d2 = await request.delete(`/api/watchlist/${T}`);
    expect(d2.status()).toBe(404);
    expect(typeof (await d2.json()).detail).toBe("string");
  });

  test("invalid ticker -> 400", async ({ request }) => {
    for (const bad of ["1ABC", "TOOLONGTICKER", "AB-C", ""]) {
      const r = await request.post("/api/watchlist", { data: { ticker: bad } });
      expect([400, 422], bad).toContain(r.status());
      if (bad !== "") expect((await r.json()).detail, bad).toBe("Invalid ticker");
    }
  });

  test("trade validation: 422 for bad quantity/side, 400 for business rules", async ({ request }) => {
    for (const data of [
      { ticker: "AAPL", side: "buy", quantity: 0 },
      { ticker: "AAPL", side: "buy", quantity: -1 },
      { ticker: "AAPL", side: "buy", quantity: 1.12345 },
      { ticker: "AAPL", side: "hold", quantity: 1 },
      { ticker: "AAPL", side: "buy" },
    ]) {
      const r = await request.post("/api/portfolio/trade", { data });
      expect(r.status(), JSON.stringify(data)).toBe(422);
    }
    const T = "TSLA";
    await flatten(request, T);
    const s = await apiTrade(request, T, "sell", 10);
    expect(s.status()).toBe(400);
    expect((await s.json()).detail).toBe("Insufficient shares: have 0, tried to sell 10");
  });

  test("trade response contract and weighted avg cost", async ({ request }) => {
    const T = "AMZN";
    await ensureWatched(request, T);
    await flatten(request, T);
    const r1 = await apiTrade(request, T, "buy", 1);
    expect(r1.status()).toBe(200);
    const b1 = await r1.json();
    expect(b1.trade).toEqual({
      id: expect.any(String),
      ticker: T,
      side: "buy",
      quantity: 1,
      price: expect.any(Number),
      executed_at: expect.stringMatching(ISO_Z),
    });
    expect(Object.keys(b1.portfolio).sort()).toEqual(
      ["cash_balance", "positions", "positions_value", "total_value", "unrealized_pnl"].sort(),
    );
    const r2 = await apiTrade(request, T, "buy", 3);
    const b2 = await r2.json();
    const pos = b2.portfolio.positions.find((p: any) => p.ticker === T);
    expect(pos.quantity).toBe(4);
    const expectedAvg = (1 * b1.trade.price + 3 * b2.trade.price) / 4;
    expect(pos.avg_cost).toBeCloseTo(expectedAvg, 1);
    expect(Object.keys(pos).sort()).toEqual(
      ["avg_cost", "current_price", "market_value", "pnl_percent", "quantity", "ticker", "unrealized_pnl"].sort(),
    );
    // Sells keep avg_cost.
    const r3 = await apiTrade(request, T, "sell", 2);
    const pos3 = (await r3.json()).portfolio.positions.find((p: any) => p.ticker === T);
    expect(pos3.avg_cost).toBe(pos.avg_cost);
    await flatten(request, T);
  });

  test("held ticker removed from watchlist keeps streaming", async ({ request, page }) => {
    const T = "BA";
    await ensureWatched(request, T);
    expect((await apiTrade(request, T, "buy", 1)).status()).toBe(200);
    expect((await request.delete(`/api/watchlist/${T}`)).status()).toBe(200);

    // Read one SSE event in the browser and check BA is still in it.
    await page.goto("/");
    const tickers: string[] = await page.evaluate(
      () =>
        new Promise((resolve, reject) => {
          const es = new EventSource("/api/stream/prices");
          const t = setTimeout(() => reject(new Error("no SSE event")), 10_000);
          es.onmessage = (e) => {
            clearTimeout(t);
            es.close();
            resolve(Object.keys(JSON.parse(e.data)));
          };
        }),
    );
    expect(tickers).toContain(T);
    await flatten(request, T);
  });

  test("SSE event shape", async ({ page }) => {
    await page.goto("/");
    const data: any = await page.evaluate(
      () =>
        new Promise((resolve, reject) => {
          const es = new EventSource("/api/stream/prices");
          const t = setTimeout(() => reject(new Error("no SSE event")), 10_000);
          es.onmessage = (e) => {
            clearTimeout(t);
            es.close();
            resolve(JSON.parse(e.data));
          };
        }),
    );
    expect(data.AAPL).toEqual({
      ticker: "AAPL",
      price: expect.any(Number),
      previous_price: expect.any(Number),
      timestamp: expect.stringMatching(/\.\d{3}Z$/),
      direction: expect.stringMatching(/^(up|down|flat)$/),
      change_percent: expect.any(Number),
    });
  });

  test("chat endpoint contract (mock)", async ({ request }) => {
    const r = await request.post("/api/chat", { data: { message: "what is my risk?" } });
    expect(r.status()).toBe(200);
    expect(await r.json()).toEqual({
      id: expect.any(String),
      role: "assistant",
      content: "This is a mock response from trading_workstation.",
      actions: { trades: [], watchlist_changes: [] },
      created_at: expect.stringMatching(ISO_Z),
    });
    const bad = await request.post("/api/chat", { data: {} });
    expect(bad.status()).toBe(422);
  });

  test("chat: removing an unwatched ticker is reported as a failed action", async ({ request }) => {
    await request.delete("/api/watchlist/XYZQ");
    const r = await request.post("/api/chat", { data: { message: "remove XYZQ" } });
    expect(r.status()).toBe(200);
    const body = await r.json();
    expect(body.content).toBe("Removing XYZQ from your watchlist.");
    expect(body.actions.watchlist_changes).toEqual([
      { ticker: "XYZQ", action: "remove", status: "failed", error: expect.any(String) },
    ]);
  });
});
