"use client";

import { flashClass, usePriceFlash } from "@/hooks/usePriceFlash";
import type { ConnectionStatus } from "@/lib/connection";
import { formatMoney, formatSignedMoney, trendClass } from "@/lib/format";

interface Props {
  totalValue: number | null;
  cash: number | null;
  unrealizedPnl: number | null;
  status: ConnectionStatus;
}

const STATUS_STYLE: Record<ConnectionStatus, { color: string; label: string }> = {
  connected: { color: "var(--color-up)", label: "Live" },
  reconnecting: { color: "var(--color-accent)", label: "Reconnecting" },
  disconnected: { color: "var(--color-down)", label: "Disconnected" },
};

export default function Header({ totalValue, cash, unrealizedPnl, status }: Props) {
  const flash = usePriceFlash(totalValue);
  const s = STATUS_STYLE[status];
  return (
    <header className="flex flex-wrap items-center gap-x-8 gap-y-2 border-b border-line bg-panel px-4 py-2">
      <div className="flex items-baseline gap-2">
        <span className="h-3 w-3 translate-y-[1px] rotate-45 bg-accent" aria-hidden="true" />
        <h1 className="text-[17px] font-bold tracking-tight text-ink">
          trading<span className="text-accent">_</span>workstation
        </h1>
      </div>

      <div className="flex items-end gap-8">
        <div className="flex flex-col leading-none">
          <span className="mb-1 text-[11px] text-muted">Portfolio value</span>
          <span
            data-testid="header-total-value"
            className={`num flash-cell -mx-1 rounded-[2px] px-1 text-[24px] font-medium text-ink ${flashClass(flash)}`}
          >
            {formatMoney(totalValue)}
          </span>
        </div>
        <div className="flex flex-col leading-none">
          <span className="mb-1 text-[11px] text-muted">Cash</span>
          <span data-testid="header-cash" className="num text-[15px] text-ink">
            {formatMoney(cash)}
          </span>
        </div>
        <div className="flex flex-col leading-none">
          <span className="mb-1 text-[11px] text-muted">Unrealized P&amp;L</span>
          <span className={`num text-[15px] ${trendClass(unrealizedPnl)}`}>
            {unrealizedPnl === null ? "—" : formatSignedMoney(unrealizedPnl)}
          </span>
        </div>
      </div>

      <div className="ml-auto flex items-center gap-2 text-[12px] text-muted" title={`Price stream: ${s.label}`}>
        <span
          data-testid="connection-status"
          data-status={status}
          aria-label={`Price stream ${s.label.toLowerCase()}`}
          role="status"
          className={`inline-block h-2.5 w-2.5 rounded-full ${status === "connected" ? "dot-live" : ""}`}
          style={{ backgroundColor: s.color, color: s.color }}
        />
        <span>{s.label}</span>
      </div>
    </header>
  );
}
