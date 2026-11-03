/**
 * Heatmap colors: red (losses) → neutral gray (0%) → green (gains).
 *
 * The scale adapts to the portfolio: its limit is the largest |P&L %| among positions,
 * clamped to [MIN_LIMIT, MAX_LIMIT]. A fixed ±5% scale leaves every tile gray in practice,
 * because simulated prices typically move well under 1% in a session.
 * Any non-zero P&L gets at least MIN_TINT intensity so its direction is always visible.
 */
export const MIN_LIMIT = 0.5;
export const MAX_LIMIT = 5;
export const MIN_TINT = 0.35;
export const FLAT_EPSILON = 0.005; // |P&L %| below this renders as neutral

export const NEUTRAL: [number, number, number] = [55, 62, 72];
export const GREEN: [number, number, number] = [22, 163, 74];
export const RED: [number, number, number] = [220, 38, 38];

/** The ± range the color scale spans for this set of P&L percentages. */
export function heatLimit(pnlPercents: number[]): number {
  const max = Math.max(0, ...pnlPercents.filter(Number.isFinite).map(Math.abs));
  return Math.min(Math.max(max, MIN_LIMIT), MAX_LIMIT);
}

export function heatColor(pnlPercent: number, limit = MAX_LIMIT): string {
  const p = Number.isFinite(pnlPercent) ? pnlPercent : 0;
  const mag = Math.abs(p);
  const t = mag < FLAT_EPSILON ? 0 : MIN_TINT + (1 - MIN_TINT) * Math.min(mag / limit, 1);
  const target = p >= 0 ? GREEN : RED;
  const mix = NEUTRAL.map((n, i) => Math.round(n + (target[i] - n) * t));
  return `rgb(${mix[0]}, ${mix[1]}, ${mix[2]})`;
}
