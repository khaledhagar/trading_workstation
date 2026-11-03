import { fmtPrice, fmtQty } from "@/lib/format";
import type { ChatActions as Actions } from "@/lib/types";

/** Inline outcome of each action the assistant requested: executed (green) or failed (red). */
export function ChatActions({ actions }: { actions: Actions | null }) {
  if (!actions) return null;
  const items = [
    ...actions.watchlist_changes.map((c, i) => ({
      key: `w${i}`,
      status: c.status,
      text: `${c.action === "add" ? "Added" : "Removed"} ${c.ticker} ${c.action === "add" ? "to" : "from"} watchlist`,
      failText: `${c.action === "add" ? "Add" : "Remove"} ${c.ticker} failed`,
      error: c.error,
    })),
    ...actions.trades.map((t, i) => ({
      key: `t${i}`,
      status: t.status,
      text: `${t.side === "buy" ? "Bought" : "Sold"} ${fmtQty(t.quantity)} ${t.ticker}${
        t.price != null ? ` @ $${fmtPrice(t.price)}` : ""
      }`,
      failText: `${t.side === "buy" ? "Buy" : "Sell"} ${fmtQty(t.quantity)} ${t.ticker} failed`,
      error: t.error,
    })),
  ];
  if (items.length === 0) return null;
  return (
    <ul className="mt-2 space-y-1">
      {items.map((it) => {
        const ok = it.status === "executed";
        return (
          <li
            key={it.key}
            data-testid="chat-action"
            data-status={it.status}
            className={`num flex items-start gap-1.5 rounded border px-2 py-1 text-[11px] ${
              ok ? "border-up/40 bg-up/10 text-up" : "border-down/40 bg-down/10 text-down"
            }`}
          >
            <span aria-hidden>{ok ? "✓" : "✕"}</span>
            <span>
              {ok ? it.text : it.failText}
              {!ok && it.error ? `: ${it.error}` : ""}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
