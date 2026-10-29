"use client";

import { useEffect, useRef } from "react";
import { AreaSeries, createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { chartOptions } from "@/lib/chartTheme";
import { formatPercent, formatPrice, trendClass } from "@/lib/format";
import type { PricePoint } from "@/lib/priceStore";
import type { PriceUpdate } from "@/lib/types";

interface Props {
  ticker: string | null;
  live: PriceUpdate | undefined;
  getHistory: (ticker: string) => readonly PricePoint[];
  historyVersion: number;
  className?: string;
}

const toData = (p: PricePoint) => ({ time: p.time as UTCTimestamp, value: p.value });

export default function MainChart({ ticker, live, getHistory, historyVersion, className = "" }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Area"> | null>(null);
  const shownTicker = useRef<string | null>(null);
  const lastTime = useRef<number>(-Infinity);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, chartOptions());
    seriesRef.current = chart.addSeries(AreaSeries, {
      lineColor: "#209dd7",
      lineWidth: 2,
      topColor: "rgba(32, 157, 215, 0.28)",
      bottomColor: "rgba(32, 157, 215, 0.02)",
      priceLineColor: "#ecad0a",
      priceLineStyle: 2,
    });
    chartRef.current = chart;
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      shownTicker.current = null;
      lastTime.current = -Infinity;
    };
  }, []);

  // Full reload on ticker change, incremental update otherwise.
  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    const points = ticker ? getHistory(ticker) : [];
    if (ticker !== shownTicker.current) {
      shownTicker.current = ticker;
      series.setData(points.map(toData));
      lastTime.current = points.length ? points[points.length - 1].time : -Infinity;
      chartRef.current?.timeScale().fitContent();
      return;
    }
    let added = false;
    for (const p of points) {
      if (p.time > lastTime.current) {
        series.update(toData(p));
        lastTime.current = p.time;
        added = true;
      }
    }
    // The chart covers everything since page load, so keep the whole buffer in view.
    if (added) chartRef.current?.timeScale().fitContent();
  }, [ticker, historyVersion, getHistory]);

  const count = ticker ? getHistory(ticker).length : 0;
  const overlay = !ticker ? "Select a ticker" : count < 2 ? "Waiting for price data…" : null;

  return (
    <section data-testid="main-chart" className={`panel min-h-[260px] ${className}`}>
      <div className="panel-title">
        <strong data-testid="main-chart-ticker" className="text-[14px] !text-accent">
          {ticker ?? "—"}
        </strong>
        {ticker && live && (
          <>
            <span className="num text-[13px] text-ink">{formatPrice(live.price)}</span>
            <span className={`num text-[12px] ${trendClass(live.change_percent)}`}>
              {formatPercent(live.change_percent)}
            </span>
          </>
        )}
        <span className="ml-auto text-[11px] font-normal text-faint">Since page load</span>
      </div>
      <div className="relative min-h-0 flex-1">
        <div ref={containerRef} className="absolute inset-0" />
        {overlay && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-[13px] text-muted">
            {overlay}
          </div>
        )}
      </div>
    </section>
  );
}
