import type { ChartPoint, ConnectionStatus, PriceTick } from "./types";

export const HISTORY_CAP = 1000;
export const STALE_MS = 5000;

export interface PriceState {
  prices: Record<string, PriceTick>;
  history: Record<string, ChartPoint[]>;
  lastTimestamp: Record<string, string>;
}

export const emptyPriceState = (): PriceState => ({ prices: {}, history: {}, lastTimestamp: {} });

/** Parse one SSE `data` payload. Returns null for malformed input. */
export function parsePriceEvent(data: string): Record<string, PriceTick> | null {
  try {
    const parsed = JSON.parse(data);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/**
 * Merge one event into the state. A history point is appended only when a ticker's
 * timestamp changes, and only if its time is strictly greater than the previous point.
 */
export function applyPriceEvent(
  state: PriceState,
  event: Record<string, PriceTick>,
  cap = HISTORY_CAP,
): PriceState {
  const prices = { ...state.prices };
  const history = { ...state.history };
  const lastTimestamp = { ...state.lastTimestamp };

  for (const [ticker, tick] of Object.entries(event)) {
    if (!tick || typeof tick.price !== "number") continue;
    prices[ticker] = tick;
    if (lastTimestamp[ticker] === tick.timestamp) continue;
    lastTimestamp[ticker] = tick.timestamp;

    const time = Date.parse(tick.timestamp) / 1000;
    if (!Number.isFinite(time)) continue;
    const buf = history[ticker] ?? [];
    if (buf.length && time <= buf[buf.length - 1].time) continue;
    const next = buf.length >= cap ? buf.slice(buf.length - cap + 1) : buf.slice();
    next.push({ time, value: tick.price });
    history[ticker] = next;
  }
  return { prices, history, lastTimestamp };
}

/** EventSource readyState values (kept local so this works without a DOM). */
export const READY = { CONNECTING: 0, OPEN: 1, CLOSED: 2 } as const;

export function deriveStatus(
  readyState: number,
  lastEventAt: number | null,
  now: number,
  staleMs = STALE_MS,
): ConnectionStatus {
  if (readyState === READY.CLOSED) return "disconnected";
  if (readyState === READY.CONNECTING) return "reconnecting";
  if (lastEventAt === null || now - lastEventAt > staleMs) return "reconnecting";
  return "connected";
}
