"use client";

import { ResponsiveContainer, Treemap } from "recharts";

import { fmtPct } from "@/lib/format";
import { heatColor, heatLimit } from "@/lib/heatmap";

import { EmptyState } from "./Panel";

interface Cell {
  name: string;
  size: number;
  pnl: number;
  limit: number;
  [key: string]: unknown;
}

interface NodeProps {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  name?: string;
  pnl?: number;
  limit?: number;
  depth?: number;
}

function HeatCell({ x = 0, y = 0, width = 0, height = 0, name, pnl = 0, limit, depth }: NodeProps) {
  if (depth === 0 || !name) return null; // root node
  const showPct = width > 54 && height > 34;
  const showName = width > 26 && height > 16;
  return (
    <g data-testid={`heat-${name}`} data-pnl={pnl.toFixed(2)}>
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        fill={heatColor(pnl, limit)}
        stroke="#0d1117"
        strokeWidth={2}
        rx={3}
      />
      {showName && (
        <text
          x={x + width / 2}
          y={y + height / 2 + (showPct ? -3 : 4)}
          textAnchor="middle"
          fill="#fff"
          fontSize={12}
          fontWeight={700}
          fontFamily="JetBrains Mono, Consolas, monospace"
        >
          {name}
        </text>
      )}
      {showPct && (
        <text
          x={x + width / 2}
          y={y + height / 2 + 13}
          textAnchor="middle"
          fill="rgba(255,255,255,0.85)"
          fontSize={11}
          fontFamily="JetBrains Mono, Consolas, monospace"
        >
          {fmtPct(pnl)}
        </text>
      )}
    </g>
  );
}

export function Heatmap({
  positions,
}: {
  positions: { ticker: string; market_value: number; pnl_percent: number }[];
}) {
  if (positions.length === 0) {
    return <EmptyState>No positions yet — buy shares with the trade bar or ask trading_workstation</EmptyState>;
  }
  const held = positions.filter((p) => p.market_value > 0);
  const limit = heatLimit(held.map((p) => p.pnl_percent));
  const data: Cell[] = held.map((p) => ({
    name: p.ticker,
    size: p.market_value,
    pnl: p.pnl_percent,
    limit,
  }));
  return (
    <div className="relative h-full w-full">
      <ResponsiveContainer width="100%" height="100%">
        <Treemap data={data} dataKey="size" isAnimationActive={false} content={<HeatCell />} />
      </ResponsiveContainer>
      <div
        data-testid="heat-legend"
        className="num pointer-events-none absolute bottom-1.5 right-1.5 flex items-center gap-1 rounded bg-bg/80 px-1.5 py-0.5 text-[9px] text-muted"
      >
        <span>{fmtPct(-limit)}</span>
        <span
          className="h-1.5 w-16 rounded-sm"
          style={{
            background: `linear-gradient(to right, ${heatColor(-limit, limit)}, ${heatColor(0, limit)}, ${heatColor(limit, limit)})`,
          }}
        />
        <span>{fmtPct(limit)}</span>
      </div>
    </div>
  );
}
