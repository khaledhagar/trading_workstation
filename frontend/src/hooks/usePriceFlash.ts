"use client";

import { useEffect, useRef, useState } from "react";

/** How long the flash color is held before the CSS transition fades it out (~500 ms). */
export const FLASH_HOLD_MS = 120;

export type Flash = "up" | "down" | null;

export function flashClass(flash: Flash): string {
  return flash === "up" ? "flash-up" : flash === "down" ? "flash-down" : "";
}

/**
 * Flashes when the price value differs from the last one seen. Compares values rather than
 * the event's `direction`, which Massive re-sends unchanged every 500 ms between polls.
 */
export function usePriceFlash(price: number | null | undefined): Flash {
  const previous = useRef<number | null | undefined>(price);
  const [flash, setFlash] = useState<Flash>(null);

  useEffect(() => {
    const old = previous.current;
    previous.current = price;
    if (old === null || old === undefined || price === null || price === undefined) return;
    if (old === price) return;
    setFlash(price > old ? "up" : "down");
    const timer = setTimeout(() => setFlash(null), FLASH_HOLD_MS);
    return () => clearTimeout(timer);
  }, [price]);

  return flash;
}
