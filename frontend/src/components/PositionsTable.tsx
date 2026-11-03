import { fmtPct, fmtPrice, fmtQty, fmtUsd, signClass } from "@/lib/format";
import type { Position } from "@/lib/types";

export function PositionsTable({
  positions,
  onSelect,
}: {
  positions: Position[];
  onSelect: (ticker: string) => void;
}) {
  return (
    <table className="w-full text-xs" data-testid="positions-table">
      <thead className="sticky top-0 bg-panel">
        <tr className="text-[10px] uppercase tracking-wider text-muted">
          <th className="py-1.5 pl-3 text-left font-medium">Ticker</th>
          <th className="py-1.5 text-right font-medium">Qty</th>
          <th className="py-1.5 text-right font-medium">Avg Cost</th>
          <th className="py-1.5 text-right font-medium">Price</th>
          <th className="py-1.5 text-right font-medium">Value</th>
          <th className="py-1.5 text-right font-medium">Unrl P&L</th>
          <th className="py-1.5 pr-3 text-right font-medium">%</th>
        </tr>
      </thead>
      <tbody>
        {positions.length === 0 ? (
          <tr>
            <td colSpan={7} className="py-6 text-center text-muted">
              No positions yet — buy shares with the trade bar or ask trading_workstation
            </td>
          </tr>
        ) : (
          positions.map((p) => (
            <tr
              key={p.ticker}
              data-testid={`position-${p.ticker}`}
              onClick={() => onSelect(p.ticker)}
              className="num cursor-pointer border-t border-border/60 hover:bg-white/[0.03]"
            >
              <td className="py-1.5 pl-3 font-sans font-semibold">{p.ticker}</td>
              <td className="py-1.5 text-right" data-testid={`position-qty-${p.ticker}`}>{fmtQty(p.quantity)}</td>
              <td className="py-1.5 text-right">{fmtPrice(p.avg_cost)}</td>
              <td className="py-1.5 text-right">{fmtPrice(p.current_price)}</td>
              <td className="py-1.5 text-right">{fmtUsd(p.market_value)}</td>
              <td className={`py-1.5 text-right ${signClass(p.unrealized_pnl)}`}>{fmtUsd(p.unrealized_pnl)}</td>
              <td className={`py-1.5 pr-3 text-right ${signClass(p.pnl_percent)}`}>{fmtPct(p.pnl_percent)}</td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}
