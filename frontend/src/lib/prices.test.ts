import { applyPriceEvent, deriveStatus, emptyPriceState, parsePriceEvent, READY } from "./prices";
import type { PriceTick } from "./types";

const tick = (ticker: string, price: number, timestamp: string): PriceTick => ({
  ticker,
  price,
  previous_price: price,
  timestamp,
  direction: "flat",
  change_percent: 0,
});

describe("parsePriceEvent", () => {
  it("parses a keyed object and rejects junk", () => {
    expect(parsePriceEvent('{"AAPL":{"ticker":"AAPL","price":1}}')?.AAPL.price).toBe(1);
    expect(parsePriceEvent("not json")).toBeNull();
    expect(parsePriceEvent("[1,2]")).toBeNull();
  });
});

describe("applyPriceEvent", () => {
  it("appends a point only when the timestamp changes", () => {
    let s = emptyPriceState();
    s = applyPriceEvent(s, { AAPL: tick("AAPL", 190, "2026-01-01T12:00:00.000Z") });
    s = applyPriceEvent(s, { AAPL: tick("AAPL", 190, "2026-01-01T12:00:00.000Z") });
    s = applyPriceEvent(s, { AAPL: tick("AAPL", 191, "2026-01-01T12:00:00.500Z") });
    expect(s.history.AAPL).toEqual([
      { time: Date.parse("2026-01-01T12:00:00.000Z") / 1000, value: 190 },
      { time: Date.parse("2026-01-01T12:00:00.500Z") / 1000, value: 191 },
    ]);
    expect(s.prices.AAPL.price).toBe(191);
  });

  it("drops points whose time is not strictly increasing", () => {
    let s = emptyPriceState();
    s = applyPriceEvent(s, { X: tick("X", 1, "2026-01-01T12:00:01.000Z") });
    s = applyPriceEvent(s, { X: tick("X", 2, "2026-01-01T12:00:00.000Z") });
    expect(s.history.X).toHaveLength(1);
  });

  it("caps the buffer", () => {
    let s = emptyPriceState();
    for (let i = 0; i < 15; i++) {
      s = applyPriceEvent(s, { X: tick("X", i + 1, new Date(1_700_000_000_000 + i * 500).toISOString()) }, 10);
    }
    expect(s.history.X).toHaveLength(10);
    expect(s.history.X[9].value).toBe(15);
    expect(s.history.X[0].value).toBe(6);
  });

  it("does not mutate the previous state", () => {
    const a = applyPriceEvent(emptyPriceState(), { X: tick("X", 1, "2026-01-01T12:00:00.000Z") });
    const b = applyPriceEvent(a, { X: tick("X", 2, "2026-01-01T12:00:01.000Z") });
    expect(a.history.X).toHaveLength(1);
    expect(b.history.X).toHaveLength(2);
  });
});

describe("deriveStatus", () => {
  const now = 100_000;
  it("maps readyState and staleness", () => {
    expect(deriveStatus(READY.OPEN, now - 1000, now)).toBe("connected");
    expect(deriveStatus(READY.OPEN, now - 5001, now)).toBe("reconnecting");
    expect(deriveStatus(READY.OPEN, null, now)).toBe("reconnecting");
    expect(deriveStatus(READY.CONNECTING, now, now)).toBe("reconnecting");
    expect(deriveStatus(READY.CLOSED, now, now)).toBe("disconnected");
  });
});
