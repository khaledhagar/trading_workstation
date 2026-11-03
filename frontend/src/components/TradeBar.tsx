"use client";

import { useEffect, useState } from "react";

export interface TradeResult {
  ok: boolean;
  message: string;
}

export function TradeBar({
  ticker: selectedTicker,
  onTrade,
}: {
  ticker: string | null;
  onTrade: (ticker: string, quantity: number, side: "buy" | "sell") => Promise<TradeResult>;
}) {
  const [ticker, setTicker] = useState(selectedTicker ?? "");
  const [qty, setQty] = useState("1");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<TradeResult | null>(null);

  useEffect(() => {
    if (selectedTicker) setTicker(selectedTicker);
  }, [selectedTicker]);

  const submit = async (side: "buy" | "sell") => {
    const t = ticker.trim();
    const q = Number(qty);
    if (!t) return setResult({ ok: false, message: "Enter a ticker" });
    if (!Number.isFinite(q) || q <= 0) return setResult({ ok: false, message: "Enter a quantity > 0" });
    setBusy(true);
    setResult(await onTrade(t, q, side));
    setBusy(false);
  };

  return (
    <form
      data-testid="trade-bar"
      onSubmit={(e) => {
        e.preventDefault();
        submit("buy");
      }}
      className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-panel px-3 py-2"
    >
      <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-accent">Trade</span>
      <input
        data-testid="trade-ticker"
        value={ticker}
        onChange={(e) => setTicker(e.target.value)}
        placeholder="Ticker"
        maxLength={10}
        className="num w-24 rounded border border-border bg-bg px-2 py-1 text-xs uppercase outline-none focus:border-blue"
      />
      <input
        data-testid="trade-qty"
        value={qty}
        onChange={(e) => setQty(e.target.value)}
        inputMode="decimal"
        placeholder="Qty"
        className="num w-24 rounded border border-border bg-bg px-2 py-1 text-xs outline-none focus:border-blue"
      />
      <button
        type="button"
        data-testid="buy-button"
        disabled={busy}
        onClick={() => submit("buy")}
        className="rounded bg-up/90 px-4 py-1 text-xs font-bold text-bg hover:bg-up disabled:opacity-50"
      >
        BUY
      </button>
      <button
        type="button"
        data-testid="sell-button"
        disabled={busy}
        onClick={() => submit("sell")}
        className="rounded bg-down/90 px-4 py-1 text-xs font-bold text-white hover:bg-down disabled:opacity-50"
      >
        SELL
      </button>
      <span className="text-[10px] text-muted">Market order · instant fill</span>
      {result && (
        <span
          data-testid="trade-result"
          className={`ml-auto truncate text-xs ${result.ok ? "text-up" : "text-down"}`}
        >
          {result.message}
        </span>
      )}
    </form>
  );
}
