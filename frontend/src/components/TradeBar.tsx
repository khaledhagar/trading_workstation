"use client";

import { useEffect, useState, type FormEvent } from "react";
import { formatMoney, formatQty } from "@/lib/format";
import type { Trade } from "@/lib/types";

interface Props {
  selected: string | null;
  priceFor: (ticker: string) => number | null;
  onTrade: (ticker: string, quantity: number, side: "buy" | "sell") => Promise<{ trade?: Trade; error?: string }>;
}

export default function TradeBar({ selected, priceFor, onTrade }: Props) {
  const [ticker, setTicker] = useState(selected ?? "");
  const [qty, setQty] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  // Clicking a ticker elsewhere fills the trade bar.
  useEffect(() => {
    if (selected) setTicker(selected);
  }, [selected]);

  const symbol = ticker.trim().toUpperCase();
  const quantity = Number(qty);
  const validQty = qty.trim() !== "" && Number.isFinite(quantity) && quantity > 0;
  const price = symbol ? priceFor(symbol) : null;
  const estimate = validQty && price !== null ? quantity * price : null;

  async function submit(side: "buy" | "sell", e?: FormEvent) {
    e?.preventDefault();
    if (!symbol || !validQty || busy) return;
    setBusy(true);
    setError(null);
    setDone(null);
    const res = await onTrade(symbol, quantity, side);
    setBusy(false);
    if (res.error) {
      setError(res.error);
    } else if (res.trade) {
      const t = res.trade;
      setDone(`${t.side === "buy" ? "Bought" : "Sold"} ${formatQty(t.quantity)} ${t.ticker} at ${formatMoney(t.price)}`);
      setQty("");
    }
  }

  return (
    <form
      onSubmit={(e) => submit("buy", e)}
      className="panel flex-row flex-wrap items-center gap-2 px-3 py-2"
      aria-label="Trade"
    >
      <span className="mr-1 text-[13px] font-semibold text-ink">Trade</span>
      <input
        data-testid="trade-ticker"
        className="field num w-24 uppercase placeholder:normal-case"
        placeholder="Ticker"
        aria-label="Ticker"
        maxLength={10}
        value={ticker}
        onChange={(e) => setTicker(e.target.value)}
      />
      <input
        data-testid="trade-quantity"
        className="field num w-24"
        placeholder="Qty"
        aria-label="Quantity"
        inputMode="decimal"
        type="number"
        min="0"
        step="any"
        value={qty}
        onChange={(e) => setQty(e.target.value)}
      />
      <button
        data-testid="trade-buy"
        type="submit"
        disabled={busy || !symbol || !validQty}
        className="h-[30px] rounded-[2px] bg-purple px-4 text-[13px] font-semibold text-white hover:bg-purple-hi disabled:opacity-40"
      >
        Buy
      </button>
      <button
        data-testid="trade-sell"
        type="button"
        onClick={() => submit("sell")}
        disabled={busy || !symbol || !validQty}
        className="h-[30px] rounded-[2px] border border-purple px-4 text-[13px] font-semibold text-ink hover:bg-purple/25 disabled:opacity-40"
      >
        Sell
      </button>
      <span className="num ml-1 text-[12px] text-muted">
        {estimate !== null ? `≈ ${formatMoney(estimate)} at market` : "Market order, fills instantly"}
      </span>
      <span className="ml-auto text-[12px]" aria-live="polite">
        {error ? (
          <span data-testid="trade-error" className="text-down">
            {error}
          </span>
        ) : done ? (
          <span className="text-up">{done}</span>
        ) : null}
      </span>
    </form>
  );
}
