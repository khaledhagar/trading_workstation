const usd = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return usd.format(value);
}

/** Signed money, e.g. "+$3.80" / "−$12.00". */
export function formatSignedMoney(value: number): string {
  if (!Number.isFinite(value)) return "—";
  const abs = usd.format(Math.abs(value));
  if (value > 0) return `+${abs}`;
  if (value < 0) return `−${abs}`;
  return abs;
}

export function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toFixed(2)}%`;
}

export function formatQty(value: number): string {
  return value.toLocaleString("en-US", { maximumFractionDigits: 4 });
}

export function trendClass(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return "text-muted";
  return value > 0 ? "text-up" : "text-down";
}
