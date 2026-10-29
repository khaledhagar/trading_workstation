import { test, expect } from "@playwright/test";
import { gotoApp, waitForPrice, getPortfolio, flatten, sendChat, openChat, getWatchlist, ensureWatched } from "./helpers";

// Requires the backend to run with LLM_MOCK=true (PLAN.md §9 mock rules).
test.describe("AI chat (mock LLM)", () => {
  test("buy via chat executes and shows the action inline", async ({ page, request }) => {
    await ensureWatched(request, "AAPL");
    await flatten(request, "AAPL");
    await gotoApp(page);
    await waitForPrice(page, "AAPL");
    const cashBefore = (await getPortfolio(request)).cash_balance;

    const body = await sendChat(page, "buy 1 AAPL");
    expect(body.role).toBe("assistant");
    expect(body.content).toBe("Buying 1 AAPL.");
    expect(body.actions.trades).toHaveLength(1);
    expect(body.actions.trades[0]).toMatchObject({ ticker: "AAPL", side: "buy", quantity: 1, status: "executed", error: null });

    await expect(page.getByTestId("chat-message-user").last()).toContainText("buy 1 AAPL");
    await expect(page.getByTestId("chat-message-assistant").last()).toContainText("Buying 1 AAPL.");
    const action = page.locator('[data-testid="chat-action"][data-status="executed"]').last();
    await expect(action).toBeVisible();
    await expect(action).toContainText("AAPL");

    // Portfolio refetched after an executed action.
    await expect(page.getByTestId("position-row-AAPL")).toBeVisible();
    const after = await getPortfolio(request);
    expect(after.cash_balance).toBeLessThan(cashBefore);

    await flatten(request, "AAPL");
  });

  test("failed trade is reported inline as failed", async ({ page, request }) => {
    await gotoApp(page);
    const cashBefore = (await getPortfolio(request)).cash_balance;
    const body = await sendChat(page, "buy 999999 TSLA");
    expect(body.actions.trades[0]).toMatchObject({ ticker: "TSLA", status: "failed" });
    expect(body.actions.trades[0].error).toMatch(/Insufficient cash/);

    const action = page.locator('[data-testid="chat-action"][data-status="failed"]').last();
    await expect(action).toBeVisible();
    await expect(action).toContainText(/Insufficient cash/);
    expect((await getPortfolio(request)).cash_balance).toBe(cashBefore);
  });

  test("LLM failure returns the apology message", async ({ page }) => {
    await gotoApp(page);
    const body = await sendChat(page, "fail");
    expect(body.content).toBe("Sorry, I couldn't process that request. Please try again.");
    expect(body.actions.trades).toEqual([]);
    expect(body.actions.watchlist_changes).toEqual([]);
    await expect(page.getByTestId("chat-message-assistant").last()).toContainText("Sorry, I couldn't process that request");
  });

  test("watchlist add/remove via chat updates the watchlist panel", async ({ page, request }) => {
    const T = "SHOP";
    await request.delete(`/api/watchlist/${T}`);
    await gotoApp(page);

    const add = await sendChat(page, `please add ${T}`);
    expect(add.actions.watchlist_changes[0]).toMatchObject({ ticker: T, action: "add", status: "executed" });
    await expect(page.getByTestId(`watchlist-row-${T}`)).toBeVisible();

    const rm = await sendChat(page, `remove ${T}`);
    expect(rm.actions.watchlist_changes[0]).toMatchObject({ ticker: T, action: "remove", status: "executed" });
    await expect(page.getByTestId(`watchlist-row-${T}`)).toHaveCount(0);
    expect((await getWatchlist(request)).map((r) => r.ticker)).not.toContain(T);
  });

  test("typing indicator shows while waiting, input disabled", async ({ page }) => {
    await gotoApp(page);
    const input = await openChat(page);
    // Delay the chat response so the waiting state is observable.
    await page.route("**/api/chat", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      await new Promise((r) => setTimeout(r, 1500));
      await route.continue();
    });
    await input.fill("hello there");
    await page.getByTestId("chat-send").click();
    await expect(page.getByTestId("chat-typing")).toBeVisible();
    await expect(input).toBeDisabled();
    await expect(page.getByTestId("chat-typing")).toHaveCount(0, { timeout: 10_000 });
    await expect(page.getByTestId("chat-message-assistant").last()).toContainText(
      "This is a mock response from trading_workstation.",
    );
    await page.unroute("**/api/chat");
  });

  test("chat history survives reload", async ({ page, request }) => {
    await gotoApp(page);
    const marker = `history check ${Date.now()}`;
    await sendChat(page, marker);
    await page.reload();
    await openChat(page);
    await expect(page.getByTestId("chat-message-user").filter({ hasText: marker })).toBeVisible();

    const hist = await (await request.get("/api/chat/history")).json();
    expect(hist.length).toBeLessThanOrEqual(50);
    const idx = hist.findIndex((m: any) => m.role === "user" && m.content === marker);
    expect(idx).toBeGreaterThanOrEqual(0);
    expect(hist[idx].actions).toBeNull();
    expect(hist[idx + 1]).toMatchObject({ role: "assistant" });
  });
});
