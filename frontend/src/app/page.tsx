"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { ChatPanel } from "@/components/ChatPanel";
import { Header } from "@/components/Header";
import { Heatmap } from "@/components/Heatmap";
import { EmptyState, Panel } from "@/components/Panel";
import { PositionsTable } from "@/components/PositionsTable";
import { TimeSeriesChart } from "@/components/TimeSeriesChart";
import { TradeBar, type TradeResult } from "@/components/TradeBar";
import { Watchlist } from "@/components/Watchlist";
import { usePriceStream } from "@/hooks/usePriceStream";
import { api, ApiError } from "@/lib/api";
import { fmtPct, fmtPrice, fmtQty, signClass } from "@/lib/format";
import { livePositions, liveTotalValue } from "@/lib/portfolio";
import type { ChartPoint, ChatMessage, Portfolio, Snapshot, WatchlistItem } from "@/lib/types";

const HISTORY_POLL_MS = 30_000;

export default function Home() {
  const { prices, history, status } = usePriceStream();
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [chatCollapsed, setChatCollapsed] = useState(false);

  const loadWatchlist = useCallback(() => api.watchlist().then(setWatchlist).catch(() => {}), []);
  const loadPortfolio = useCallback(() => api.portfolio().then(setPortfolio).catch(() => {}), []);
  const loadHistory = useCallback(() => api.history().then(setSnapshots).catch(() => {}), []);

  useEffect(() => {
    loadWatchlist();
    loadPortfolio();
    loadHistory();
    const t = setInterval(loadHistory, HISTORY_POLL_MS);
    return () => clearInterval(t);
  }, [loadWatchlist, loadPortfolio, loadHistory]);

  // Auto-select the first watchlist ticker; drop the selection if it disappears.
  useEffect(() => {
    const tickers = watchlist.map((w) => w.ticker);
    const held = portfolio?.positions.map((p) => p.ticker) ?? [];
    if (selected && (tickers.includes(selected) || held.includes(selected))) return;
    setSelected(tickers[0] ?? null);
  }, [watchlist, portfolio, selected]);

  const totalValue = liveTotalValue(portfolio, prices);
  const positions = useMemo(() => livePositions(portfolio, prices), [portfolio, prices]);
  const unrealized = portfolio ? positions.reduce((s, p) => s + p.unrealized_pnl, 0) : null;

  const pnlData: ChartPoint[] = useMemo(() => {
    const out: ChartPoint[] = [];
    for (const s of snapshots) {
      const time = Date.parse(s.recorded_at) / 1000;
      if (!out.length || time > out[out.length - 1].time) out.push({ time, value: s.total_value });
    }
    return out;
  }, [snapshots]);

  const handleAdd = async (ticker: string): Promise<string | null> => {
    try {
      setWatchlist(await api.addTicker(ticker));
      return null;
    } catch (e) {
      return e instanceof Error ? e.message : "Could not add ticker";
    }
  };

  const handleRemove = async (ticker: string) => {
    try {
      setWatchlist(await api.removeTicker(ticker));
    } catch {
      loadWatchlist();
    }
  };

  const handleTrade = async (ticker: string, quantity: number, side: "buy" | "sell"): Promise<TradeResult> => {
    try {
      const { trade, portfolio: next } = await api.trade(ticker, quantity, side);
      setPortfolio(next);
      loadHistory();
      if (!watchlist.some((w) => w.ticker === trade.ticker)) loadWatchlist();
      return {
        ok: true,
        message: `${side === "buy" ? "Bought" : "Sold"} ${fmtQty(trade.quantity)} ${trade.ticker} @ $${fmtPrice(trade.price)}`,
      };
    } catch (e) {
      return { ok: false, message: e instanceof ApiError ? e.message : "Trade failed" };
    }
  };

  const handleChatActions = (msg: ChatMessage) => {
    const a = msg.actions;
    if (!a) return;
    if (a.trades.some((t) => t.status === "executed")) {
      loadPortfolio();
      loadHistory();
      loadWatchlist(); // buys can auto-add tickers
    } else if (a.watchlist_changes.some((c) => c.status === "executed")) {
      loadWatchlist();
      loadPortfolio();
    }
  };

  const selectedTick = selected ? prices[selected] : undefined;
  const selectedHistory = selected ? history[selected] ?? [] : [];

  return (
    <div className="flex h-screen min-h-[640px] flex-col">
      <Header
        totalValue={totalValue}
        cash={portfolio?.cash_balance ?? null}
        pnl={unrealized}
        status={status}
      />
      <main className="flex min-h-0 flex-1 gap-2 p-2">
        <div className="w-[320px] shrink-0">
          <Watchlist
            items={watchlist}
            prices={prices}
            history={history}
            selected={selected}
            onSelect={setSelected}
            onAdd={handleAdd}
            onRemove={handleRemove}
          />
        </div>

        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <Panel
            title={selected ? `${selected} · Live` : "Chart"}
            testId="main-chart"
            className="min-h-[220px] flex-[1.3]"
            right={
              selectedTick && (
                <div className="num flex items-baseline gap-3 text-xs">
                  <span className="text-sm font-semibold">{fmtPrice(selectedTick.price)}</span>
                  <span className={signClass(selectedTick.change_percent)}>
                    {fmtPct(selectedTick.change_percent)}
                  </span>
                </div>
              )
            }
          >
            {!selected ? (
              <EmptyState>Select a ticker</EmptyState>
            ) : selectedHistory.length < 2 ? (
              <EmptyState>Waiting for price data…</EmptyState>
            ) : (
              <TimeSeriesChart data={selectedHistory} color="#209dd7" resetKey={selected} />
            )}
          </Panel>

          <TradeBar ticker={selected} onTrade={handleTrade} />

          <div className="flex min-h-[200px] flex-1 gap-2">
            <Panel title="Portfolio Heatmap" testId="heatmap" className="flex-1" bodyClassName="p-1">
              <Heatmap positions={positions} />
            </Panel>
            <Panel title="Portfolio Value" testId="pnl-chart" className="flex-1">
              {pnlData.length < 2 ? (
                <EmptyState>Collecting portfolio history…</EmptyState>
              ) : (
                <TimeSeriesChart data={pnlData} color="#ecad0a" />
              )}
            </Panel>
          </div>

          <Panel title="Positions" testId="positions" className="max-h-[30%] min-h-[110px]" bodyClassName="overflow-y-auto">
            <PositionsTable positions={positions} onSelect={setSelected} />
          </Panel>
        </div>

        <ChatPanel
          onActions={handleChatActions}
          collapsed={chatCollapsed}
          onToggle={() => setChatCollapsed((c) => !c)}
        />
      </main>
    </div>
  );
}
