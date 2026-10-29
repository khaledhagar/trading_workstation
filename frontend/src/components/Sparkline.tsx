import type { PricePoint } from "@/lib/priceStore";

interface Props {
  ticker: string;
  points: readonly PricePoint[];
  width?: number;
  height?: number;
}

/** Hand-rolled inline SVG sparkline; blank until there are two points. */
export default function Sparkline({ ticker, points, width = 76, height = 22 }: Props) {
  let polyline = "";
  let stroke = "var(--color-muted)";
  if (points.length >= 2) {
    let min = Infinity;
    let max = -Infinity;
    for (const p of points) {
      if (p.value < min) min = p.value;
      if (p.value > max) max = p.value;
    }
    const range = max - min || 1;
    const step = width / (points.length - 1);
    polyline = points
      .map((p, i) => `${(i * step).toFixed(1)},${(height - 1 - ((p.value - min) / range) * (height - 2)).toFixed(1)}`)
      .join(" ");
    const first = points[0].value;
    const last = points[points.length - 1].value;
    stroke = last > first ? "var(--color-up)" : last < first ? "var(--color-down)" : "var(--color-muted)";
  }
  return (
    <svg
      data-testid={`sparkline-${ticker}`}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden="true"
      className="block"
    >
      {/* Always present; empty (blank) until there are two points. */}
      <polyline
        points={polyline}
        fill="none"
        stroke={stroke}
        strokeWidth={1.25}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
