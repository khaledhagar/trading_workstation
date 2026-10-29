import type { PriceEvent } from "./types";

export interface PricePoint {
  /** Seconds since epoch (Lightweight Charts UTCTimestamp); may be fractional. */
  time: number;
  value: number;
}

export const HISTORY_CAP = 1000;

/**
 * Capped per-ticker price history built from SSE events.
 * A point is appended only when the ticker's timestamp changes, and only if its
 * time is strictly greater than the previous point's (a Lightweight Charts requirement).
 */
export class PriceHistoryStore {
  private buffers = new Map<string, PricePoint[]>();
  private lastTimestamp = new Map<string, string>();

  constructor(private cap: number = HISTORY_CAP) {}

  /** Returns the tickers whose history gained a point. */
  ingest(event: PriceEvent): string[] {
    const changed: string[] = [];
    for (const [key, update] of Object.entries(event)) {
      if (!update || typeof update.price !== "number" || !update.timestamp) continue;
      const ticker = update.ticker ?? key;
      if (this.lastTimestamp.get(ticker) === update.timestamp) continue;
      this.lastTimestamp.set(ticker, update.timestamp);

      const time = Date.parse(update.timestamp) / 1000;
      if (!Number.isFinite(time)) continue;
      let buf = this.buffers.get(ticker);
      if (!buf) {
        buf = [];
        this.buffers.set(ticker, buf);
      }
      const last = buf[buf.length - 1];
      if (last && time <= last.time) continue;
      buf.push({ time, value: update.price });
      if (buf.length > this.cap) buf.splice(0, buf.length - this.cap);
      changed.push(ticker);
    }
    return changed;
  }

  get(ticker: string): readonly PricePoint[] {
    return this.buffers.get(ticker) ?? [];
  }
}
