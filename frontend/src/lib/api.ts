import type { ChatMessage, Portfolio, Snapshot, TradeResponse, WatchlistRow } from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Turn FastAPI's `detail` (a string, or a list of validation errors for 422) into one message. */
export function detailToMessage(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    return detail
      .map((d) =>
        d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : String(d),
      )
      .join("; ");
  }
  return `Request failed (${status})`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError("Can't reach the server. Check that the backend is running.", 0);
  }
  if (!res.ok) {
    let detail: unknown = undefined;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* body was not JSON */
    }
    throw new ApiError(detailToMessage(detail, res.status), res.status);
  }
  return (await res.json()) as T;
}

export function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export const api = {
  portfolio: () => request<Portfolio>("/api/portfolio"),
  history: () => request<Snapshot[]>("/api/portfolio/history"),
  trade: (ticker: string, quantity: number, side: "buy" | "sell") =>
    request<TradeResponse>("/api/portfolio/trade", {
      method: "POST",
      body: JSON.stringify({ ticker, quantity, side }),
    }),
  watchlist: () => request<WatchlistRow[]>("/api/watchlist"),
  addTicker: (ticker: string) =>
    request<WatchlistRow[]>("/api/watchlist", { method: "POST", body: JSON.stringify({ ticker }) }),
  removeTicker: (ticker: string) =>
    request<WatchlistRow[]>(`/api/watchlist/${encodeURIComponent(ticker)}`, { method: "DELETE" }),
  chat: (message: string) =>
    request<ChatMessage>("/api/chat", { method: "POST", body: JSON.stringify({ message }) }),
  chatHistory: () => request<ChatMessage[]>("/api/chat/history"),
};
