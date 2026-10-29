import { ColorType, CrosshairMode, type DeepPartial, type ChartOptions, type Time } from "lightweight-charts";

function toDate(time: Time): Date {
  return new Date((typeof time === "number" ? time : 0) * 1000);
}

/** Shared Lightweight Charts styling. The default TradingView attribution logo stays on. */
export function chartOptions(): DeepPartial<ChartOptions> {
  return {
    autoSize: true,
    layout: {
      background: { type: ColorType.Solid, color: "transparent" },
      textColor: "#7e8b9c",
      fontFamily: '"IBM Plex Mono", ui-monospace, monospace',
      fontSize: 11,
      attributionLogo: true,
    },
    grid: {
      vertLines: { color: "#1b2532" },
      horzLines: { color: "#1b2532" },
    },
    rightPriceScale: { borderColor: "#243041" },
    timeScale: {
      borderColor: "#243041",
      timeVisible: true,
      secondsVisible: true,
      tickMarkFormatter: (time: Time) =>
        toDate(time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }),
    },
    localization: {
      timeFormatter: (time: Time) => toDate(time).toLocaleTimeString([], { hour12: false }),
    },
    crosshair: { mode: CrosshairMode.Magnet },
  };
}
