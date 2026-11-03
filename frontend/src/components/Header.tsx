import { fmtUsd, signClass } from "@/lib/format";
import type { ConnectionStatus } from "@/lib/types";

const DOT: Record<ConnectionStatus, { color: string; label: string }> = {
  connected: { color: "bg-up shadow-[0_0_8px_var(--color-up)]", label: "Live" },
  reconnecting: { color: "bg-accent shadow-[0_0_8px_var(--color-accent)]", label: "Reconnecting" },
  disconnected: { color: "bg-down shadow-[0_0_8px_var(--color-down)]", label: "Disconnected" },
};

export function Header({
  totalValue,
  cash,
  pnl,
  status,
}: {
  totalValue: number | null;
  cash: number | null;
  pnl: number | null;
  status: ConnectionStatus;
}) {
  const dot = DOT[status];
  return (
    <header className="flex h-12 shrink-0 items-center gap-6 border-b border-border bg-panel-2 px-4">
      <div className="flex items-baseline gap-2">
        <span className="text-base font-bold tracking-tight text-accent">trading_workstation</span>
        <span className="hidden text-[10px] uppercase tracking-[0.2em] text-muted sm:inline">
          AI Trading Terminal
        </span>
      </div>
      <div className="ml-auto flex items-center gap-6">
        <Stat label="Portfolio" value={fmtUsd(totalValue)} testId="total-value" big />
        <Stat label="Unrealized P&L" value={fmtUsd(pnl)} testId="header-pnl" className={signClass(pnl)} />
        <Stat label="Cash" value={fmtUsd(cash)} testId="cash-balance" />
        <div
          className="flex items-center gap-2 text-[11px] text-muted"
          data-testid="connection-status"
          data-status={status}
          title={dot.label}
        >
          <span className={`h-2.5 w-2.5 rounded-full ${dot.color}`} />
          <span className="hidden md:inline">{dot.label}</span>
        </div>
      </div>
    </header>
  );
}

function Stat({
  label,
  value,
  testId,
  big,
  className = "",
}: {
  label: string;
  value: string;
  testId: string;
  big?: boolean;
  className?: string;
}) {
  return (
    <div className="flex flex-col items-end leading-tight">
      <span className="text-[9px] uppercase tracking-[0.16em] text-muted">{label}</span>
      <span data-testid={testId} className={`num ${big ? "text-base font-semibold" : "text-sm"} ${className}`}>
        {value}
      </span>
    </div>
  );
}
