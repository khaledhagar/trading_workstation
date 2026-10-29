/** Heatmap color scale: red (≤ −5%) → neutral gray (0%) → green (≥ +5%), linear, clamped. */
export const HEATMAP_CLAMP = 5;

export type RGB = [number, number, number];
export const NEUTRAL: RGB = [58, 66, 80];
export const GAIN: RGB = [22, 163, 98];
export const LOSS: RGB = [214, 54, 64];

function mix(a: RGB, b: RGB, t: number): RGB {
  return [0, 1, 2].map((i) => Math.round(a[i] + (b[i] - a[i]) * t)) as RGB;
}

export function pnlColorRgb(pnlPercent: number): RGB {
  const pct = Number.isFinite(pnlPercent) ? pnlPercent : 0;
  const clamped = Math.max(-HEATMAP_CLAMP, Math.min(HEATMAP_CLAMP, pct));
  const t = Math.abs(clamped) / HEATMAP_CLAMP;
  return mix(NEUTRAL, clamped >= 0 ? GAIN : LOSS, t);
}

export function pnlColor(pnlPercent: number): string {
  const [r, g, b] = pnlColorRgb(pnlPercent);
  return `rgb(${r}, ${g}, ${b})`;
}
