"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  deriveStatus,
  ES_CLOSED,
  RECONNECT_MS,
  type ConnectionStatus,
} from "@/lib/connection";
import { PriceHistoryStore, type PricePoint } from "@/lib/priceStore";
import type { PriceEvent } from "@/lib/types";

export interface PriceStream {
  /** Latest event: every tracked ticker that has a price. */
  prices: PriceEvent;
  status: ConnectionStatus;
  /** Bumps whenever any ticker's history gains a point. */
  historyVersion: number;
  getHistory: (ticker: string) => readonly PricePoint[];
}

/**
 * Subscribes to the SSE price stream. EventSource retries on its own while CONNECTING;
 * once it gives up (CLOSED) we open a fresh one every RECONNECT_MS until it connects.
 * A 1-second timer re-evaluates the connection status (5-second staleness rule).
 */
export function usePriceStream(url = "/api/stream/prices"): PriceStream {
  const storeRef = useRef<PriceHistoryStore | null>(null);
  if (storeRef.current === null) storeRef.current = new PriceHistoryStore();
  const [prices, setPrices] = useState<PriceEvent>({});
  const [status, setStatus] = useState<ConnectionStatus>("reconnecting");
  const [historyVersion, setHistoryVersion] = useState(0);

  useEffect(() => {
    let es: EventSource | null = null;
    let closedAt: number | null = null;
    let lastEventAt: number | null = null;

    const evaluate = () => {
      if (!es) return;
      const now = Date.now();
      if (es.readyState === ES_CLOSED) {
        if (closedAt === null) {
          closedAt = now;
        } else if (now - closedAt >= RECONNECT_MS) {
          es.close();
          connect();
        }
      }
      setStatus(deriveStatus(es.readyState, lastEventAt, now));
    };

    const connect = () => {
      closedAt = null;
      const source = new EventSource(url);
      es = source;
      source.onopen = evaluate;
      source.onerror = evaluate;
      source.onmessage = (e: MessageEvent<string>) => {
        let data: unknown;
        try {
          data = JSON.parse(e.data);
        } catch {
          return;
        }
        if (!data || typeof data !== "object" || Array.isArray(data)) return;
        const event = data as PriceEvent;
        lastEventAt = Date.now();
        const changed = storeRef.current!.ingest(event);
        setPrices(event);
        if (changed.length > 0) setHistoryVersion((v) => v + 1);
        evaluate();
      };
    };

    connect();
    const timer = setInterval(evaluate, 1000);
    return () => {
      clearInterval(timer);
      es?.close();
      es = null;
    };
  }, [url]);

  const getHistory = useCallback((ticker: string) => storeRef.current!.get(ticker), []);

  return { prices, status, historyVersion, getHistory };
}
