"use client";

import { useState } from "react";

import { usePriceFlash } from "@/hooks/usePriceFlash";
import { fmtPct, fmtPrice, signClass } from "@/lib/format";
import type { ChartPoint, PriceTick, WatchlistItem } from "@/lib/types";

import { EmptyState, Panel } from "./Panel";
import { Sparkline } from "./Sparkline";

function Row({
  item,
  tick,
  history,
  selected,
  onSelect,
  onRemove,
}: {
  item: WatchlistItem;
  tick: PriceTick | undefined;
  history: ChartPoint[] | undefined;
  selected: boolean;
  onSelect: () => void;
  onRemove: () => void;
}) {
  const price = tick?.price ?? item.price;
  const change = tick?.change_percent ?? item.change_percent;
  const flash = usePriceFlash(price);
  return (
    <tr
      data-testid={`watch-row-${item.ticker}`}
      onClick={onSelect}
      className={`group cursor-pointer border-b border-border/60 ${
        selected ? "bg-blue/10 shadow-[inset_2px_0_0_var(--color-blue)]" : "hover:bg-white/[0.03]"
      }`}
    >
      <td className="py-1.5 pl-3 text-xs font-semibold tracking-wide">{item.ticker}</td>
      <td className="py-1.5 text-right">
        <span data-testid={`price-${item.ticker}`} className={`num rounded px-1 text-xs ${flash}`}>
          {fmtPrice(price)}
        </span>
      </td>
      <td className={`num py-1.5 pr-2 text-right text-xs ${signClass(change)}`}>{fmtPct(change)}</td>
      <td className="py-1 pr-1">{price != null && <Sparkline points={history} width={72} height={22} />}</td>
      <td className="w-6 pr-2 text-right">
        <button
          aria-label={`Remove ${item.ticker}`}
          data-testid={`remove-${item.ticker}`}
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="text-muted opacity-0 transition hover:text-down group-hover:opacity-100 focus:opacity-100"
        >
          ×
        </button>
      </td>
    </tr>
  );
}

export function Watchlist({
  items,
  prices,
  history,
  selected,
  onSelect,
  onAdd,
  onRemove,
}: {
  items: WatchlistItem[];
  prices: Record<string, PriceTick>;
  history: Record<string, ChartPoint[]>;
  selected: string | null;
  onSelect: (ticker: string) => void;
  onAdd: (ticker: string) => Promise<string | null>;
  onRemove: (ticker: string) => void;
}) {
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const t = input.trim();
    if (!t) return;
    setBusy(true);
    const err = await onAdd(t);
    setBusy(false);
    setError(err);
    if (!err) setInput("");
  };

  return (
    <Panel title="Watchlist" testId="watchlist" className="h-full" bodyClassName="flex flex-col">
      <form onSubmit={submit} className="flex gap-2 border-b border-border p-2">
        <input
          data-testid="watch-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Add ticker…"
          maxLength={10}
          className="num min-w-0 flex-1 rounded border border-border bg-bg px-2 py-1 text-xs uppercase outline-none focus:border-blue"
        />
        <button
          type="submit"
          disabled={busy}
          data-testid="watch-add"
          className="rounded bg-purple px-3 py-1 text-xs font-semibold text-white hover:brightness-110 disabled:opacity-50"
        >
          Add
        </button>
      </form>
      {error && <p className="px-3 py-1 text-[11px] text-down" data-testid="watch-error">{error}</p>}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {items.length === 0 ? (
          <EmptyState>Your watchlist is empty — add a ticker above or ask trading_workstation</EmptyState>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="text-[10px] uppercase tracking-wider text-muted">
                <th className="py-1 pl-3 text-left font-medium">Sym</th>
                <th className="py-1 text-right font-medium">Last</th>
                <th className="py-1 pr-2 text-right font-medium">Chg</th>
                <th className="py-1 font-medium" />
                <th />
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <Row
                  key={item.ticker}
                  item={item}
                  tick={prices[item.ticker]}
                  history={history[item.ticker]}
                  selected={selected === item.ticker}
                  onSelect={() => onSelect(item.ticker)}
                  onRemove={() => onRemove(item.ticker)}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Panel>
  );
}
