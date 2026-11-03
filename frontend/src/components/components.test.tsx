import { act, render, renderHook, screen } from "@testing-library/react";

import { FLASH_MS, usePriceFlash } from "@/hooks/usePriceFlash";

import { ChatActions } from "./ChatActions";

describe("usePriceFlash", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("applies the up/down class on change and removes it afterwards", () => {
    const { result, rerender } = renderHook(({ p }) => usePriceFlash(p), { initialProps: { p: 100 } });
    expect(result.current).toBe("");
    rerender({ p: 101 });
    expect(result.current).toBe("flash-up");
    act(() => vi.advanceTimersByTime(FLASH_MS));
    expect(result.current).toBe("");
    rerender({ p: 99 });
    expect(result.current).toBe("flash-down flash-alt");
    act(() => vi.advanceTimersByTime(FLASH_MS));
    expect(result.current).toBe("");
  });

  it("replays the animation on consecutive same-direction moves", () => {
    const { result, rerender } = renderHook(({ p }) => usePriceFlash(p), { initialProps: { p: 100 } });
    rerender({ p: 101 });
    const first = result.current;
    rerender({ p: 102 });
    expect(result.current).not.toBe(first);
    expect(result.current).toContain("flash-up");
  });

  it("does not flash when the price is unchanged or missing", () => {
    const { result, rerender } = renderHook(({ p }: { p: number | null }) => usePriceFlash(p), {
      initialProps: { p: null as number | null },
    });
    rerender({ p: 100 });
    expect(result.current).toBe("");
    rerender({ p: 100 });
    expect(result.current).toBe("");
  });
});

describe("ChatActions", () => {
  it("renders executed and failed outcomes distinctly", () => {
    render(
      <ChatActions
        actions={{
          trades: [
            { ticker: "AAPL", side: "buy", quantity: 10, status: "executed", price: 190.12, error: null },
            { ticker: "TSLA", side: "sell", quantity: 3, status: "failed", price: null, error: "Insufficient shares: have 0, tried to sell 3" },
          ],
          watchlist_changes: [{ ticker: "PYPL", action: "add", status: "failed", error: "Unknown ticker: PYPL" }],
        }}
      />,
    );
    const items = screen.getAllByTestId("chat-action");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveAttribute("data-status", "failed");
    expect(items[0]).toHaveTextContent("Add PYPL failed: Unknown ticker: PYPL");
    expect(items[1]).toHaveAttribute("data-status", "executed");
    expect(items[1]).toHaveTextContent("Bought 10 AAPL @ $190.12");
    expect(items[1].className).toContain("text-up");
    expect(items[2]).toHaveTextContent("Sell 3 TSLA failed: Insufficient shares");
    expect(items[2].className).toContain("text-down");
  });

  it("renders nothing without actions", () => {
    const { container } = render(<ChatActions actions={{ trades: [], watchlist_changes: [] }} />);
    expect(container).toBeEmptyDOMElement();
  });
});
