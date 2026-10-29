import { describe, expect, it } from "vitest";
import { GAIN, LOSS, NEUTRAL, pnlColor, pnlColorRgb } from "./heatmap";

describe("heatmap color scale", () => {
  it("is neutral gray at 0%", () => {
    expect(pnlColorRgb(0)).toEqual(NEUTRAL);
  });

  it("is full green at +5% and clamps above", () => {
    expect(pnlColorRgb(5)).toEqual(GAIN);
    expect(pnlColorRgb(12)).toEqual(GAIN);
  });

  it("is full red at −5% and clamps below", () => {
    expect(pnlColorRgb(-5)).toEqual(LOSS);
    expect(pnlColorRgb(-40)).toEqual(LOSS);
  });

  it("interpolates linearly in between", () => {
    const mid = (a: number, b: number) => Math.round(a + (b - a) * 0.5);
    expect(pnlColorRgb(2.5)).toEqual([0, 1, 2].map((i) => mid(NEUTRAL[i], GAIN[i])));
    expect(pnlColorRgb(-2.5)).toEqual([0, 1, 2].map((i) => mid(NEUTRAL[i], LOSS[i])));
  });

  it("gets greener as gains grow and redder as losses grow", () => {
    expect(pnlColorRgb(4)[1]).toBeGreaterThan(pnlColorRgb(1)[1]);
    expect(pnlColorRgb(-4)[0]).toBeGreaterThan(pnlColorRgb(-1)[0]);
  });

  it("treats NaN as neutral and formats as rgb()", () => {
    expect(pnlColorRgb(Number.NaN)).toEqual(NEUTRAL);
    expect(pnlColor(0)).toBe(`rgb(${NEUTRAL.join(", ")})`);
  });
});
