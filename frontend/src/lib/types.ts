export type Direction = "up" | "down" | "flat";

export interface PriceTick {
  ticker: string;
  price: number;
  previous_price: number;
  timestamp: string;
  direction: Direction;
  change_percent: number;
}

export interface WatchlistItem {
  ticker: string;
  price: number | null;
  previous_price: number | null;
  timestamp: string | null;
  direction: Direction | null;
  change_percent: number | null;
}

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

export interface Snapshot {
  total_value: number;
  recorded_at: string;
}

export type ActionStatus = "executed" | "failed";

export interface TradeOutcome {
  ticker: string;
  side: "buy" | "sell";
  quantity: number;
  status: ActionStatus;
  price: number | null;
  error: string | null;
}

export interface WatchlistOutcome {
  ticker: string;
  action: "add" | "remove";
  status: ActionStatus;
  error: string | null;
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

export interface ChartPoint {
  time: number; // seconds since epoch (may be fractional)
  value: number;
}

export type ConnectionStatus = "connected" | "reconnecting" | "disconnected";
