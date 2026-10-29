export type Direction = "up" | "down" | "flat";

export interface PriceUpdate {
  ticker: string;
  price: number;
  previous_price: number;
  timestamp: string;
  direction: Direction;
  change_percent: number;
}

export type PriceEvent = Record<string, PriceUpdate>;

export interface Position {
  ticker: string;
  quantity: number;
  avg_cost: number;
  current_price: number;
  market_value: number;
  unrealized_pnl: number;
  pnl_percent: number;
}

export interface Portfolio {
  cash_balance: number;
  positions_value: number;
  total_value: number;
  unrealized_pnl: number;
  positions: Position[];
}

export interface Trade {
  id: string;
  ticker: string;
  side: "buy" | "sell";
  quantity: number;
  price: number;
  executed_at: string;
}

export interface TradeResponse {
  trade: Trade;
  portfolio: Portfolio;
}

export interface Snapshot {
  total_value: number;
  recorded_at: string;
}

export interface WatchlistRow {
  ticker: string;
  price: number | null;
  previous_price: number | null;
  direction: Direction | null;
  change_percent: number | null;
  timestamp: string | null;
}

export type ActionStatus = "executed" | "failed";

export interface TradeOutcome {
  ticker: string;
  side: "buy" | "sell";
  quantity: number;
  status: ActionStatus;
  price?: number | null;
  error?: string | null;
}

export interface WatchlistOutcome {
  ticker: string;
  action: "add" | "remove";
  status: ActionStatus;
  error?: string | null;
}

export interface ChatActions {
  trades: TradeOutcome[];
  watchlist_changes: WatchlistOutcome[];
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  actions: ChatActions | null;
  created_at: string;
}
