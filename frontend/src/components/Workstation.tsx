"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePriceStream } from "@/hooks/usePriceStream";
import { api, errorMessage } from "@/lib/api";
import { computeTotalValue, livePosition } from "@/lib/portfolio";
import type { ChatActions, Portfolio, Snapshot, WatchlistRow } from "@/lib/types";
import ChatPanel from "./ChatPanel";
import Header from "./Header";
import Heatmap from "./Heatmap";
import MainChart from "./MainChart";
import PnlChart from "./PnlChart";
import PositionsTable from "./PositionsTable";
import Toasts, { useToasts } from "./Toasts";
import TradeBar from "./TradeBar";
import Watchlist from "./Watchlist";

const HISTORY_REFRESH_MS = 30_000;

export default function Workstation() {
  const stream = usePriceStream();
  const { prices } = stream;
  const { toasts, pushError, dismiss } = useToasts();
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [watchlist, setWatchlist] = useState<WatchlistRow[] | null>(null);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(true);

  const refreshPortfolio = useCallback(
    () => api.portfolio().then(setPortfolio).catch((e) => pushError(errorMessage(e))),
    [pushError],
  );
  const refreshWatchlist = useCallback(
    () => api.watchlist().then(setWatchlist).catch((e) => pushError(errorMessage(e))),
    [pushError],
  );
  const refreshHistory = useCallback(
    () => api.history().then(setSnapshots).catch(() => undefined),
    [],
  );

  useEffect(() => {
    refreshPortfolio();
    refreshWatchlist();
    refreshHistory();
    const timer = setInterval(refreshHistory, HISTORY_REFRESH_MS);
    return () => clearInterval(timer);
  }, [refreshPortfolio, refreshWatchlist, refreshHistory]);

  // Auto-select the first watchlist ticker; keep the selection valid as the watchlist changes.
  useEffect(() => {
    if (!watchlist) return;
    const held = portfolio?.positions.some((p) => p.ticker === selected) ?? false;
    if (selected && (watchlist.some((r) => r.ticker === selected) || held)) return;
    setSelected(watchlist[0]?.ticker ?? null);
  }, [watchlist, portfolio, selected]);

  const positions = useMemo(
    () => (portfolio ? portfolio.positions.map((p) => livePosition(p, prices)) : []),
    [portfolio, prices],
  );
  const totalValue = computeTotalValue(portfolio, prices);
  const unrealized = portfolio ? positions.reduce((s, p) => s + p.unrealized_pnl, 0) : null;

  const priceFor = useCallback(
    (ticker: string) =>
      prices[ticker]?.price ?? watchlist?.find((r) => r.ticker === ticker)?.price ?? null,
    [prices, watchlist],
  );

  const handleTrade = useCallback(
    async (ticker: string, quantity: number, side: "buy" | "sell") => {
      try {
        const res = await api.trade(ticker, quantity, side);
        setPortfolio(res.portfolio);
        if (!watchlist?.some((r) => r.ticker === res.trade.ticker)) refreshWatchlist();
        refreshHistory();
        return { trade: res.trade };
      } catch (e) {
        const message = errorMessage(e);
        pushError(message);
        return { error: message };
      }
    },
    [watchlist, refreshWatchlist, refreshHistory, pushError],
  );

  const handleAdd = useCallback(
    async (ticker: string) => {
      try {
        setWatchlist(await api.addTicker(ticker));
        setSelected(ticker);
        return true;
      } catch (e) {
        pushError(errorMessage(e));
        return false;
      }
    },
    [pushError],
  );

  const handleRemove = useCallback(
    async (ticker: string) => {
      try {
        setWatchlist(await api.removeTicker(ticker));
      } catch (e) {
        pushError(errorMessage(e));
      }
    },
    [pushError],
  );

  const handleChatActions = useCallback(
    (actions: ChatActions) => {
      const tradeDone = actions.trades?.some((t) => t.status === "executed") ?? false;
      const watchDone = actions.watchlist_changes?.some((w) => w.status === "executed") ?? false;
      if (!tradeDone && !watchDone) return;
      refreshPortfolio();
      refreshHistory();
      // A buy of an unwatched ticker auto-adds it, so trades can change the watchlist too.
      refreshWatchlist();
    },
    [refreshPortfolio, refreshHistory, refreshWatchlist],
  );

  const heatmapItems = positions.map((p) => ({
    ticker: p.ticker,
    marketValue: p.market_value,
    pnlPercent: p.pnl_percent,
  }));

  return (
    <div className="flex min-h-screen flex-col lg:h-screen lg:overflow-hidden">
      <Header
        totalValue={totalValue}
        cash={portfolio?.cash_balance ?? null}
        unrealizedPnl={unrealized}
        status={stream.status}
      />
      <main className="flex flex-1 flex-col gap-2 p-2 lg:min-h-0 lg:flex-row">
        <div className="lg:w-[330px] lg:shrink-0 lg:[&>section]:h-full">
          <Watchlist
            rows={watchlist}
            prices={prices}
            getHistory={stream.getHistory}
            selected={selected}
            onSelect={setSelected}
            onAdd={handleAdd}
            onRemove={handleRemove}
          />
        </div>

        <div className="flex min-w-0 flex-1 flex-col gap-2 lg:min-h-0">
          <MainChart
            className="lg:flex-[1.35]"
            ticker={selected}
            live={selected ? prices[selected] : undefined}
            getHistory={stream.getHistory}
            historyVersion={stream.historyVersion}
          />
          <TradeBar selected={selected} priceFor={priceFor} onTrade={handleTrade} />
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2 lg:min-h-0 lg:flex-1">
            <Heatmap items={heatmapItems} onSelect={setSelected} />
            <PnlChart snapshots={snapshots} />
          </div>
          <PositionsTable className="lg:flex-[0.85]" positions={positions} onSelect={setSelected} />
        </div>

        <div className="flex lg:min-h-0">
          <ChatPanel
            open={chatOpen}
            onToggle={() => setChatOpen((o) => !o)}
            onActions={handleChatActions}
            onError={pushError}
          />
        </div>
      </main>
      <Toasts toasts={toasts} onDismiss={dismiss} />
    </div>
  );
}
