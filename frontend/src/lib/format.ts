const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

export const fmtUsd = (v: number | null | undefined) => (v == null ? "—" : usd.format(v));

export const fmtPrice = (v: number | null | undefined) =>
  v == null ? "—" : v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const fmtPct = (v: number | null | undefined) =>
  v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;

export const fmtQty = (v: number) =>
  v.toLocaleString("en-US", { maximumFractionDigits: 4 });

export const signClass = (v: number | null | undefined) =>
  v == null || v === 0 ? "text-muted" : v > 0 ? "text-up" : "text-down";
