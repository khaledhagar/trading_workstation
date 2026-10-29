"use client";

import { ResponsiveContainer, Treemap } from "recharts";
import { formatPercent } from "@/lib/format";
import { pnlColor } from "@/lib/heatmap";

export interface HeatmapItem {
  ticker: string;
  marketValue: number;
  pnlPercent: number;
}

interface CellProps {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  depth?: number;
  name?: string;
  pnl?: number;
  onSelect?: (ticker: string) => void;
}

function Cell({ x = 0, y = 0, width = 0, height = 0, depth, name, pnl = 0, onSelect }: CellProps) {
  if (depth !== 1 || !name) return null;
  const roomForPnl = width > 54 && height > 36;
  const roomForTicker = width > 26 && height > 16;
  const pct = Math.round(pnl * 100) / 100;
  return (
    <g
      data-testid={`heatmap-cell-${name}`}
      data-pnl-percent={pct}
      style={{ cursor: "pointer" }}
      onClick={() => onSelect?.(name)}
    >
      <rect x={x} y={y} width={width} height={height} fill={pnlColor(pnl)} stroke="#121923" strokeWidth={2} />
      <title>{`${name} ${formatPercent(pnl)}`}</title>
      {roomForTicker && (
        <text
          x={x + width / 2}
          y={y + height / 2 + (roomForPnl ? -3 : 4)}
          textAnchor="middle"
          fill="#f3f6fa"
          fontSize={Math.min(16, Math.max(11, width / 6))}
          fontWeight={600}
          fontFamily="Barlow Semi Condensed, sans-serif"
        >
          {name}
        </text>
      )}
      {roomForPnl && (
        <text
          x={x + width / 2}
          y={y + height / 2 + 13}
          textAnchor="middle"
          fill="rgba(243,246,250,0.85)"
          fontSize={11}
          fontFamily="IBM Plex Mono, monospace"
        >
          {formatPercent(pnl)}
        </text>
      )}
    </g>
  );
}

export default function Heatmap({
  items,
  onSelect,
  className = "",
}: {
  items: HeatmapItem[];
  onSelect: (ticker: string) => void;
  className?: string;
}) {
  const data = items
    .filter((i) => i.marketValue > 0)
    .map((i) => ({ name: i.ticker, size: i.marketValue, pnl: i.pnlPercent }));
  return (
    <section data-testid="heatmap" className={`panel min-h-[200px] ${className}`}>
      <div className="panel-title">
        <strong>Positions heatmap</strong>
        <span className="ml-auto text-[11px] font-normal text-faint">Sized by weight, colored by P&amp;L</span>
      </div>
      <div className="relative min-h-0 flex-1 p-1">
        {data.length === 0 ? (
          <div
            data-testid="heatmap-empty"
            className="flex h-full items-center justify-center px-6 text-center text-[13px] leading-relaxed text-muted"
          >
            No positions yet — buy shares with the trade bar or ask trading_workstation
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <Treemap
              data={data}
              dataKey="size"
              isAnimationActive={false}
              content={<Cell onSelect={onSelect} />}
            />
          </ResponsiveContainer>
        )}
      </div>
    </section>
  );
}
