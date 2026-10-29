import { formatMoney, formatQty } from "@/lib/format";
import type { ChatActions as Actions, TradeOutcome, WatchlistOutcome } from "@/lib/types";

export function describeTrade(t: TradeOutcome): string {
  const qty = formatQty(t.quantity);
  if (t.status === "executed") {
    const verb = t.side === "buy" ? "Bought" : "Sold";
    return `${verb} ${qty} ${t.ticker}${typeof t.price === "number" ? ` at ${formatMoney(t.price)}` : ""}`;
  }
  const verb = t.side === "buy" ? "Buy" : "Sell";
  return `${verb} ${qty} ${t.ticker} failed${t.error ? `: ${t.error}` : ""}`;
}

export function describeWatchlist(w: WatchlistOutcome): string {
  if (w.status === "executed") {
    return w.action === "add" ? `Added ${w.ticker} to watchlist` : `Removed ${w.ticker} from watchlist`;
  }
  const verb = w.action === "add" ? "Add" : "Remove";
  return `${verb} ${w.ticker} failed${w.error ? `: ${w.error}` : ""}`;
}

function ActionLine({ status, text }: { status: "executed" | "failed"; text: string }) {
  const ok = status === "executed";
  return (
    <li
      data-testid="chat-action"
      data-status={status}
      className={`flex items-start gap-2 rounded-[2px] border-l-2 px-2 py-1 text-[12.5px] leading-snug ${
        ok ? "border-up bg-up/10 text-ink" : "border-down bg-down/10 text-down"
      }`}
    >
      <span aria-hidden="true" className={ok ? "text-up" : "text-down"}>
        {ok ? "✓" : "✕"}
      </span>
      <span>{text}</span>
    </li>
  );
}

/** Inline outcomes of the actions the assistant requested: watchlist changes first, then trades. */
export default function ChatActions({ actions }: { actions: Actions | null | undefined }) {
  if (!actions) return null;
  const changes = actions.watchlist_changes ?? [];
  const trades = actions.trades ?? [];
  if (changes.length === 0 && trades.length === 0) return null;
  return (
    <ul className="mt-2 flex flex-col gap-1">
      {changes.map((w, i) => (
        <ActionLine key={`w${i}`} status={w.status} text={describeWatchlist(w)} />
      ))}
      {trades.map((t, i) => (
        <ActionLine key={`t${i}`} status={t.status} text={describeTrade(t)} />
      ))}
    </ul>
  );
}
