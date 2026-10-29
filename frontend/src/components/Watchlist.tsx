"use client";

import { useState, type FormEvent } from "react";
import { flashClass, usePriceFlash } from "@/hooks/usePriceFlash";
import { formatPercent, formatPrice, trendClass } from "@/lib/format";
import type { PricePoint } from "@/lib/priceStore";
import type { PriceUpdate, WatchlistRow } from "@/lib/types";
import Sparkline from "./Sparkline";

interface Props {
  rows: WatchlistRow[] | null;
  prices: Record<string, PriceUpdate | undefined>;
  getHistory: (ticker: string) => readonly PricePoint[];
  selected: string | null;
  onSelect: (ticker: string) => void;
  onAdd: (ticker: string) => Promise<boolean>;
  onRemove: (ticker: string) => void;
}

function Row({
  row,
  live,
  points,
  selected,
  onSelect,
  onRemove,
}: {
  row: WatchlistRow;
  live: PriceUpdate | undefined;
  points: readonly PricePoint[];
  selected: boolean;
  onSelect: () => void;
  onRemove: () => void;
}) {
  const t = row.ticker;
  const price = live?.price ?? row.price;
  const change = live?.change_percent ?? row.change_percent;
  const flash = usePriceFlash(price);
  return (
    <li
      data-testid={`watchlist-row-${t}`}
      aria-current={selected ? "true" : undefined}
      className={`group grid cursor-pointer grid-cols-[minmax(0,1fr)_76px_74px_58px_18px] items-center gap-2 border-b border-l-2 border-b-line-soft py-[5px] pl-2.5 pr-1.5 ${
        selected ? "border-l-accent bg-raised" : "border-l-transparent hover:bg-raised/60"
      }`}
      onClick={onSelect}
    >
      <button
        type="button"
        onClick={onSelect}
        className={`truncate text-left text-[14px] font-semibold ${selected ? "text-accent" : "text-ink"}`}
      >
        {t}
      </button>
      <Sparkline ticker={t} points={points} />
      <span
        data-testid={`price-${t}`}
        className={`num flash-cell rounded-[2px] px-1 text-right text-[13px] text-ink ${flashClass(flash)}`}
      >
        {formatPrice(price)}
      </span>
      <span data-testid={`change-${t}`} className={`num text-right text-[12px] ${trendClass(change)}`}>
        {formatPercent(change)}
      </span>
      <button
        type="button"
        data-testid={`remove-${t}`}
        aria-label={`Remove ${t} from watchlist`}
        title={`Remove ${t}`}
        onClick={(e) => {
          e.stopPropagation();
          onRemove();
        }}
        className="text-[15px] leading-none text-faint opacity-50 hover:text-down group-hover:opacity-100 focus-visible:opacity-100"
      >
        ×
      </button>
    </li>
  );
}

export default function Watchlist({ rows, prices, getHistory, selected, onSelect, onAdd, onRemove }: Props) {
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const ticker = input.trim().toUpperCase();
    if (!ticker || busy) return;
    setBusy(true);
    const ok = await onAdd(ticker);
    setBusy(false);
    if (ok) setInput("");
  }

  return (
    <section data-testid="watchlist" className="panel min-h-[320px]">
      <div className="panel-title">
        <strong>Watchlist</strong>
        <span className="num ml-auto text-[11px] text-faint">{rows ? rows.length : ""}</span>
      </div>
      <form onSubmit={submit} className="flex gap-1.5 border-b border-line p-2">
        <input
          data-testid="watchlist-add-input"
          className="field num min-w-0 flex-1 uppercase placeholder:normal-case"
          placeholder="Add ticker"
          aria-label="Ticker to add"
          value={input}
          maxLength={10}
          onChange={(e) => setInput(e.target.value)}
        />
        <button
          data-testid="watchlist-add-button"
          type="submit"
          disabled={busy || !input.trim()}
          className="h-[30px] rounded-[2px] bg-purple px-3 text-[13px] font-semibold text-white hover:bg-purple-hi disabled:opacity-40"
        >
          Add
        </button>
      </form>
      <div className="grid grid-cols-[minmax(0,1fr)_76px_74px_58px_18px] gap-2 px-2.5 pb-1 pt-1.5 text-[11px] text-faint">
        <span>Symbol</span>
        <span>Trend</span>
        <span className="text-right">Last</span>
        <span className="text-right">Chg</span>
        <span />
      </div>
      <ul className="min-h-0 flex-1 overflow-y-auto">
        {rows === null ? null : rows.length === 0 ? (
          <li data-testid="watchlist-empty" className="px-3 py-6 text-center text-[13px] leading-relaxed text-muted">
            Your watchlist is empty — add a ticker above or ask trading_workstation
          </li>
        ) : (
          rows.map((row) => (
            <Row
              key={row.ticker}
              row={row}
              live={prices[row.ticker]}
              points={getHistory(row.ticker)}
              selected={row.ticker === selected}
              onSelect={() => onSelect(row.ticker)}
              onRemove={() => onRemove(row.ticker)}
            />
          ))
        )}
      </ul>
    </section>
  );
}
