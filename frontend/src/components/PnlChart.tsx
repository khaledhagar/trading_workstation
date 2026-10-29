"use client";

import { useEffect, useMemo, useRef } from "react";
import { BaselineSeries, createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { chartOptions } from "@/lib/chartTheme";
import { formatMoney, formatSignedMoney, trendClass } from "@/lib/format";
import type { Snapshot } from "@/lib/types";

/** Snapshots → strictly increasing chart points (duplicates within a second are dropped). */
export function snapshotsToPoints(snapshots: Snapshot[]) {
  const out: { time: UTCTimestamp; value: number }[] = [];
  for (const s of snapshots) {
    const time = Date.parse(s.recorded_at) / 1000;
    if (!Number.isFinite(time)) continue;
    const last = out[out.length - 1];
    if (last && time <= last.time) continue;
    out.push({ time: time as UTCTimestamp, value: s.total_value });
  }
  return out;
}

export default function PnlChart({ snapshots, className = "" }: { snapshots: Snapshot[]; className?: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Baseline"> | null>(null);
  const points = useMemo(() => snapshotsToPoints(snapshots), [snapshots]);
  const base = points[0]?.value ?? 0;
  const last = points[points.length - 1]?.value ?? null;
  const ready = points.length >= 2;

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      ...chartOptions(),
      timeScale: { ...chartOptions().timeScale, secondsVisible: false },
    });
    seriesRef.current = chart.addSeries(BaselineSeries, {
      lineWidth: 2,
      topLineColor: "#22c47a",
      topFillColor1: "rgba(34, 196, 122, 0.25)",
      topFillColor2: "rgba(34, 196, 122, 0.02)",
      bottomLineColor: "#ef4f5a",
      bottomFillColor1: "rgba(239, 79, 90, 0.02)",
      bottomFillColor2: "rgba(239, 79, 90, 0.25)",
      priceLineVisible: false,
    });
    chartRef.current = chart;
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    series.applyOptions({ baseValue: { type: "price", price: base } });
    series.setData(points);
    chartRef.current?.timeScale().fitContent();
  }, [points, base]);

  const change = last !== null ? last - base : null;

  return (
    <section data-testid="pnl-chart" className={`panel min-h-[200px] ${className}`}>
      <div className="panel-title">
        <strong>Portfolio value</strong>
        {ready && last !== null && (
          <>
            <span className="num ml-auto text-[12px] text-ink">{formatMoney(last)}</span>
            <span className={`num text-[12px] ${trendClass(change)}`}>{formatSignedMoney(change ?? 0)}</span>
          </>
        )}
      </div>
      <div className="relative min-h-0 flex-1">
        <div ref={containerRef} className="absolute inset-0" style={{ visibility: ready ? "visible" : "hidden" }} />
        {!ready && (
          <div
            data-testid="pnl-chart-empty"
            className="absolute inset-0 flex items-center justify-center text-[13px] text-muted"
          >
            Collecting portfolio history…
          </div>
        )}
      </div>
    </section>
  );
}
