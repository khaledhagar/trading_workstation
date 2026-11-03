"use client";

import { useEffect, useRef, useState } from "react";

export const FLASH_MS = 500;

/**
 * Returns "flash-up" / "flash-down" for FLASH_MS after `price` changes, else "".
 * Consecutive changes alternate an extra "flash-alt" class, which switches to an identical
 * animation name so the browser replays it (re-applying the same class would not).
 */
export function usePriceFlash(price: number | null | undefined): string {
  const prev = useRef<number | null | undefined>(price);
  const parity = useRef(false);
  const [cls, setCls] = useState("");

  useEffect(() => {
    const before = prev.current;
    prev.current = price;
    if (price == null || before == null || price === before) return;
    parity.current = !parity.current;
    setCls(`${price > before ? "flash-up" : "flash-down"}${parity.current ? "" : " flash-alt"}`);
    const t = setTimeout(() => setCls(""), FLASH_MS);
    return () => clearTimeout(t);
  }, [price]);

  return cls;
}
