"use client";

import { useEffect, useRef, useState } from "react";

import {
  applyPriceEvent,
  deriveStatus,
  emptyPriceState,
  parsePriceEvent,
  READY,
  type PriceState,
} from "@/lib/prices";
import type { ConnectionStatus } from "@/lib/types";

export const RECONNECT_MS = 5000;

/**
 * Subscribes to /api/stream/prices. Keeps latest prices and capped per-ticker history,
 * and derives the header's connection status (PLAN.md §10 Connection Status).
 */
export function usePriceStream(url = "/api/stream/prices") {
  const [state, setState] = useState<PriceState>(emptyPriceState);
  const [status, setStatus] = useState<ConnectionStatus>("reconnecting");
  const sourceRef = useRef<EventSource | null>(null);
  const lastEventAt = useRef<number | null>(null);

  useEffect(() => {
    let disposed = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const refresh = () => {
      const es = sourceRef.current;
      setStatus(deriveStatus(es ? es.readyState : READY.CLOSED, lastEventAt.current, Date.now()));
    };

    const connect = () => {
      if (disposed) return;
      const es = new EventSource(url);
      sourceRef.current = es;
      es.onmessage = (ev) => {
        const event = parsePriceEvent(ev.data);
        if (!event) return;
        lastEventAt.current = Date.now();
        setState((s) => applyPriceEvent(s, event));
        refresh();
      };
      es.onopen = refresh;
      // The browser retries on its own while CONNECTING; the 1s timer below handles CLOSED.
      es.onerror = refresh;
    };

    connect();
    const ticker = setInterval(() => {
      refresh();
      const es = sourceRef.current;
      // CLOSED means the browser gave up: open a new EventSource after RECONNECT_MS.
      if (es && es.readyState === READY.CLOSED && !reconnectTimer) {
        reconnectTimer = setTimeout(() => {
          reconnectTimer = null;
          connect();
        }, RECONNECT_MS);
      }
    }, 1000);

    return () => {
      disposed = true;
      clearInterval(ticker);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      sourceRef.current?.close();
    };
  }, [url]);

  return { prices: state.prices, history: state.history, status };
}
