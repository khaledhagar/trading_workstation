import type { ChartPoint } from "@/lib/types";

/** Tiny inline SVG polyline. No chart library per row. */
export function Sparkline({
  points,
  width = 96,
  height = 26,
  maxPoints = 120,
}: {
  points: ChartPoint[] | undefined;
  width?: number;
  height?: number;
  maxPoints?: number;
}) {
  const pts = (points ?? []).slice(-maxPoints);
  if (pts.length < 2) return <svg width={width} height={height} aria-hidden />;
  const values = pts.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const step = width / (pts.length - 1);
  const coords = pts
    .map((p, i) => `${(i * step).toFixed(1)},${(height - 2 - ((p.value - min) / range) * (height - 4)).toFixed(1)}`)
    .join(" ");
  const up = values[values.length - 1] >= values[0];
  return (
    <svg width={width} height={height} aria-hidden data-testid="sparkline">
      <polyline
        points={coords}
        fill="none"
        stroke={up ? "var(--color-up)" : "var(--color-down)"}
        strokeWidth={1.4}
        strokeLinejoin="round"
      />
    </svg>
  );
}
