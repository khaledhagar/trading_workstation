import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ChatActions from "./ChatActions";

describe("ChatActions", () => {
  it("renders nothing for user messages or empty actions", () => {
    const { container, rerender } = render(<ChatActions actions={null} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<ChatActions actions={{ trades: [], watchlist_changes: [] }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows executed and failed outcomes with their status", () => {
    render(
      <ChatActions
        actions={{
          trades: [
            { ticker: "AAPL", side: "buy", quantity: 10, status: "executed", price: 190.12, error: null },
            {
              ticker: "TSLA",
              side: "sell",
              quantity: 5,
              status: "failed",
              price: null,
              error: "Insufficient shares: have 0, tried to sell 5",
            },
          ],
          watchlist_changes: [{ ticker: "PYPL", action: "add", status: "failed", error: "Unknown ticker" }],
        }}
      />,
    );
    const items = screen.getAllByTestId("chat-action");
    expect(items).toHaveLength(3);

    // Watchlist changes are listed first (they're applied first).
    expect(items[0]).toHaveAttribute("data-status", "failed");
    expect(items[0]).toHaveTextContent("Add PYPL failed: Unknown ticker");

    expect(items[1]).toHaveAttribute("data-status", "executed");
    expect(items[1]).toHaveTextContent("Bought 10 AAPL at $190.12");
    expect(items[1]).toHaveClass("text-ink");

    expect(items[2]).toHaveAttribute("data-status", "failed");
    expect(items[2]).toHaveTextContent("Sell 5 TSLA failed: Insufficient shares: have 0, tried to sell 5");
    expect(items[2]).toHaveClass("text-down");
  });

  it("describes executed watchlist removals and fractional sells", () => {
    render(
      <ChatActions
        actions={{
          trades: [{ ticker: "NVDA", side: "sell", quantity: 0.5, status: "executed", price: 1200, error: null }],
          watchlist_changes: [{ ticker: "NFLX", action: "remove", status: "executed", error: null }],
        }}
      />,
    );
    expect(screen.getByText("Removed NFLX from watchlist")).toBeInTheDocument();
    expect(screen.getByText("Sold 0.5 NVDA at $1,200.00")).toBeInTheDocument();
  });
});
