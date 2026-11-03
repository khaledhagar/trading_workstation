import type { ChatMessage, Portfolio, Snapshot, Trade, WatchlistItem } from "./types";

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

function detailMessage(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  // FastAPI 422s carry a list of validation errors.
  if (Array.isArray(detail) && detail.length && typeof detail[0]?.msg === "string") {
    return detail[0].msg.replace(/^Value error, /, "");
  }
  return `Request failed (${status})`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail: unknown = null;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detailMessage(detail, res.status), res.status);
  }
  return res.json() as Promise<T>;
}

export const api = {
  portfolio: () => request<Portfolio>("/api/portfolio"),
  history: () => request<Snapshot[]>("/api/portfolio/history"),
  trade: (ticker: string, quantity: number, side: "buy" | "sell") =>
    request<{ trade: Trade; portfolio: Portfolio }>("/api/portfolio/trade", {
      method: "POST",
      body: JSON.stringify({ ticker, quantity, side }),
    }),
  watchlist: () => request<WatchlistItem[]>("/api/watchlist"),
  addTicker: (ticker: string) =>
    request<WatchlistItem[]>("/api/watchlist", { method: "POST", body: JSON.stringify({ ticker }) }),
  removeTicker: (ticker: string) =>
    request<WatchlistItem[]>(`/api/watchlist/${encodeURIComponent(ticker)}`, { method: "DELETE" }),
  chat: (message: string) =>
    request<ChatMessage>("/api/chat", { method: "POST", body: JSON.stringify({ message }) }),
  chatHistory: () => request<ChatMessage[]>("/api/chat/history"),
};
