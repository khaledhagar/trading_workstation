import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "trading_workstation — AI Trading Workstation",
  description: "Live prices, a simulated portfolio and an AI trading copilot",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
