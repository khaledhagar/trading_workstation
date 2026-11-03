"use client";

import {
  AreaSeries,
  ColorType,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

import type { ChartPoint } from "@/lib/types";

interface Props {
  data: ChartPoint[];
  color: string;
  /** Change to reset the visible range (e.g. when switching tickers). */
  resetKey?: string;
}

/** Lightweight Charts area series. Attribution is left enabled (license requirement). */
export function TimeSeriesChart({ data, color, resetKey }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Area"> | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#8b949e",
        fontFamily: "JetBrains Mono, Consolas, monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(42, 51, 65, 0.5)" },
        horzLines: { color: "rgba(42, 51, 65, 0.5)" },
      },
      rightPriceScale: { borderColor: "#2a3341" },
      timeScale: { borderColor: "#2a3341", timeVisible: true, secondsVisible: true },
      crosshair: { horzLine: { color: "#ecad0a55" }, vertLine: { color: "#ecad0a55" } },
    });
    chartRef.current = chart;
    seriesRef.current = chart.addSeries(AreaSeries, {
      lineColor: color,
      topColor: `${color}55`,
      bottomColor: `${color}05`,
      lineWidth: 2,
      priceLineColor: color,
    });
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, [color]);

  // The whole buffer since page load (≤ 1,000 points) is always kept in view.
  useEffect(() => {
    seriesRef.current?.setData(
      data.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })),
    );
    chartRef.current?.timeScale().fitContent();
  }, [data, resetKey]);

  return <div ref={containerRef} className="h-full w-full" />;
}
