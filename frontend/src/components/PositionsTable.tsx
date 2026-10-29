"use client";

import { formatMoney, formatPercent, formatPrice, formatQty, formatSignedMoney, trendClass } from "@/lib/format";
import type { Position } from "@/lib/types";

const HEAD = ["Ticker", "Qty", "Avg cost", "Price", "Mkt value", "Unrealized P&L", "%"];

export default function PositionsTable({
  positions,
  onSelect,
  className = "",
}: {
  positions: Position[];
  onSelect: (ticker: string) => void;
  className?: string;
}) {
  return (
    <section className={`panel min-h-[160px] ${className}`}>
      <div className="panel-title">
        <strong>Positions</strong>
        <span className="num ml-auto text-[11px] text-faint">{positions.length || ""}</span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <table data-testid="positions-table" className="w-full border-collapse text-[13px]">
          <thead className="sticky top-0 bg-panel">
            <tr className="text-[11px] text-faint">
              {HEAD.map((h, i) => (
                <th key={h} className={`px-3 py-1.5 font-normal ${i === 0 ? "text-left" : "text-right"}`}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {positions.length === 0 ? (
              <tr>
                <td data-testid="positions-empty" colSpan={HEAD.length} className="px-3 py-5 text-center text-muted">
                  No positions yet — buy shares with the trade bar or ask trading_workstation
                </td>
              </tr>
            ) : (
              positions.map((p) => (
                <tr
                  key={p.ticker}
                  data-testid={`position-row-${p.ticker}`}
                  onClick={() => onSelect(p.ticker)}
                  className="cursor-pointer border-t border-line-soft hover:bg-raised/60"
                >
                  <td className="px-3 py-1.5 text-left font-semibold">{p.ticker}</td>
                  <td data-testid={`position-qty-${p.ticker}`} className="num px-3 py-1.5 text-right">
                    {formatQty(p.quantity)}
                  </td>
                  <td className="num px-3 py-1.5 text-right text-muted">{formatPrice(p.avg_cost)}</td>
                  <td className="num px-3 py-1.5 text-right">{formatPrice(p.current_price)}</td>
                  <td className="num px-3 py-1.5 text-right">{formatMoney(p.market_value)}</td>
                  <td
                    data-testid={`position-pnl-${p.ticker}`}
                    className={`num px-3 py-1.5 text-right ${trendClass(p.unrealized_pnl)}`}
                  >
                    {formatSignedMoney(p.unrealized_pnl)}
                  </td>
                  <td className={`num px-3 py-1.5 text-right ${trendClass(p.pnl_percent)}`}>
                    {formatPercent(p.pnl_percent)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
