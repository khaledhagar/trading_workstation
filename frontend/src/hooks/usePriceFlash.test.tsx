import { act, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FLASH_HOLD_MS, flashClass, usePriceFlash } from "./usePriceFlash";

function FlashCell({ price }: { price: number | null }) {
  const flash = usePriceFlash(price);
  return <span data-testid="cell" className={`flash-cell ${flashClass(flash)}`} />;
}

describe("usePriceFlash", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("does not flash on the first price", () => {
    const { result } = renderHook(({ p }) => usePriceFlash(p), { initialProps: { p: 100 as number | null } });
    expect(result.current).toBeNull();
  });

  it("does not flash when a price first arrives after null", () => {
    const { result, rerender } = renderHook(({ p }) => usePriceFlash(p), {
      initialProps: { p: null as number | null },
    });
    rerender({ p: 100 });
    expect(result.current).toBeNull();
  });

  it("applies flash-up on an uptick and removes it afterwards", () => {
    const { rerender } = render(<FlashCell price={100} />);
    rerender(<FlashCell price={101} />);
    expect(screen.getByTestId("cell")).toHaveClass("flash-up");
    act(() => vi.advanceTimersByTime(FLASH_HOLD_MS + 1));
    expect(screen.getByTestId("cell")).not.toHaveClass("flash-up");
    expect(screen.getByTestId("cell")).toHaveClass("flash-cell");
  });

  it("applies flash-down on a downtick and removes it afterwards", () => {
    const { rerender } = render(<FlashCell price={100} />);
    rerender(<FlashCell price={99.5} />);
    expect(screen.getByTestId("cell")).toHaveClass("flash-down");
    act(() => vi.advanceTimersByTime(FLASH_HOLD_MS + 1));
    expect(screen.getByTestId("cell")).not.toHaveClass("flash-down");
  });

  it("does not flash when the same price is re-sent", () => {
    const { rerender } = render(<FlashCell price={100} />);
    rerender(<FlashCell price={100} />);
    expect(screen.getByTestId("cell")).not.toHaveClass("flash-up");
    expect(screen.getByTestId("cell")).not.toHaveClass("flash-down");
  });
});
