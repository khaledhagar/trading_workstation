import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { deriveStatus, ES_CLOSED, ES_CONNECTING, ES_OPEN } from "@/lib/connection";
import { PriceHistoryStore } from "@/lib/priceStore";
import type { PriceUpdate } from "@/lib/types";
import { usePriceStream } from "./usePriceStream";

function upd(ticker: string, price: number, timestamp: string): PriceUpdate {
  return { ticker, price, previous_price: price, timestamp, direction: "flat", change_percent: 0 };
}

class MockEventSource {
  static instances: MockEventSource[] = [];
  readyState = ES_CONNECTING;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  closed = false;
  constructor(public url: string) {
    MockEventSource.instances.push(this);
  }
  close() {
    this.closed = true;
    this.readyState = ES_CLOSED;
  }
  open() {
    this.readyState = ES_OPEN;
    this.onopen?.();
  }
  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
  fail() {
    this.readyState = ES_CLOSED;
    this.onerror?.();
  }
}

describe("PriceHistoryStore", () => {
  it("appends only when the timestamp changes", () => {
    const store = new PriceHistoryStore();
    store.ingest({ AAPL: upd("AAPL", 190, "2026-01-01T12:00:00.000Z") });
    store.ingest({ AAPL: upd("AAPL", 190, "2026-01-01T12:00:00.000Z") });
    store.ingest({ AAPL: upd("AAPL", 191, "2026-01-01T12:00:00.500Z") });
    expect(store.get("AAPL").map((p) => p.value)).toEqual([190, 191]);
    expect(store.get("AAPL")[1].time).toBe(Date.parse("2026-01-01T12:00:00.500Z") / 1000);
  });

  it("drops points whose time is not strictly increasing", () => {
    const store = new PriceHistoryStore();
    store.ingest({ AAPL: upd("AAPL", 190, "2026-01-01T12:00:01.000Z") });
    const changed = store.ingest({ AAPL: upd("AAPL", 189, "2026-01-01T12:00:00.000Z") });
    expect(changed).toEqual([]);
    expect(store.get("AAPL")).toHaveLength(1);
  });

  it("caps each ticker's buffer, keeping the newest points", () => {
    const store = new PriceHistoryStore(3);
    for (let i = 0; i < 5; i++) {
      store.ingest({ MSFT: upd("MSFT", 400 + i, new Date(Date.UTC(2026, 0, 1, 12, 0, i)).toISOString()) });
    }
    expect(store.get("MSFT").map((p) => p.value)).toEqual([402, 403, 404]);
  });

  it("keeps separate buffers per ticker", () => {
    const store = new PriceHistoryStore();
    store.ingest({
      AAPL: upd("AAPL", 190, "2026-01-01T12:00:00.000Z"),
      MSFT: upd("MSFT", 410, "2026-01-01T12:00:00.000Z"),
    });
    expect(store.get("AAPL")).toHaveLength(1);
    expect(store.get("MSFT")).toHaveLength(1);
    expect(store.get("NFLX")).toHaveLength(0);
  });
});

describe("deriveStatus", () => {
  const now = 100_000;
  it("is connected when open with a recent event", () => {
    expect(deriveStatus(ES_OPEN, now - 1000, now)).toBe("connected");
  });
  it("is reconnecting when open but stale for more than 5 s", () => {
    expect(deriveStatus(ES_OPEN, now - 5001, now)).toBe("reconnecting");
  });
  it("is reconnecting when open with no event yet, or connecting", () => {
    expect(deriveStatus(ES_OPEN, null, now)).toBe("reconnecting");
    expect(deriveStatus(ES_CONNECTING, now, now)).toBe("reconnecting");
  });
  it("is disconnected when closed", () => {
    expect(deriveStatus(ES_CLOSED, now, now)).toBe("disconnected");
  });
});

describe("usePriceStream", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    MockEventSource.instances = [];
    vi.stubGlobal("EventSource", MockEventSource);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("parses events into latest prices and history buffers", () => {
    const { result } = renderHook(() => usePriceStream("/api/stream/prices"));
    const es = MockEventSource.instances[0];
    expect(es.url).toBe("/api/stream/prices");
    act(() => {
      es.open();
      es.emit({ AAPL: upd("AAPL", 190.12, "2026-01-01T12:00:00.000Z") });
      es.emit({ AAPL: upd("AAPL", 190.5, "2026-01-01T12:00:00.500Z") });
      es.emit({ AAPL: upd("AAPL", 190.5, "2026-01-01T12:00:00.500Z") });
    });
    expect(result.current.prices.AAPL.price).toBe(190.5);
    expect(result.current.getHistory("AAPL").map((p) => p.value)).toEqual([190.12, 190.5]);
    expect(result.current.status).toBe("connected");
  });

  it("ignores malformed event data", () => {
    const { result } = renderHook(() => usePriceStream());
    const es = MockEventSource.instances[0];
    act(() => {
      es.open();
      es.onmessage?.({ data: "not json" });
    });
    expect(result.current.prices).toEqual({});
  });

  it("goes yellow after 5 s without events, green again when data resumes", () => {
    const { result } = renderHook(() => usePriceStream());
    const es = MockEventSource.instances[0];
    act(() => {
      es.open();
      es.emit({ AAPL: upd("AAPL", 190, "2026-01-01T12:00:00.000Z") });
    });
    expect(result.current.status).toBe("connected");
    act(() => vi.advanceTimersByTime(6000));
    expect(result.current.status).toBe("reconnecting");
    act(() => es.emit({ AAPL: upd("AAPL", 191, "2026-01-01T12:00:06.000Z") }));
    expect(result.current.status).toBe("connected");
  });

  it("starts as reconnecting while connecting", () => {
    const { result } = renderHook(() => usePriceStream());
    expect(result.current.status).toBe("reconnecting");
  });

  it("shows red when closed and opens a new EventSource after 5 s", () => {
    const { result } = renderHook(() => usePriceStream());
    const first = MockEventSource.instances[0];
    act(() => first.fail());
    expect(result.current.status).toBe("disconnected");
    act(() => vi.advanceTimersByTime(4000));
    expect(MockEventSource.instances).toHaveLength(1);
    act(() => vi.advanceTimersByTime(2000));
    expect(MockEventSource.instances).toHaveLength(2);
    expect(first.closed).toBe(true);
    const second = MockEventSource.instances[1];
    act(() => {
      second.open();
      second.emit({ AAPL: upd("AAPL", 190, "2026-01-01T12:00:00.000Z") });
    });
    expect(result.current.status).toBe("connected");
  });

  it("closes the connection on unmount", () => {
    const { unmount } = renderHook(() => usePriceStream());
    const es = MockEventSource.instances[0];
    unmount();
    expect(es.closed).toBe(true);
  });
});
