/** Types for v37.0 Quant Agent Schedule message system. */

export type MessageType =
  | "buy_signal"
  | "sell_signal"
  | "risk_alert"
  | "market_watch"
  | "hold_reminder"
  // v37.0 quant schedule types
  | "pre_market"
  | "call_auction"
  | "intraday_signal"
  | "late_session"
  | "post_market"
  | "holiday_intel"
  // v39.0 global intelligence types
  | "global_intelligence"
  | "intelligence_digest"
  | "global_pulse"
  | "market_pulse"

export interface StockRecommendation {
  symbol: string
  name: string
  direction?: "BUY" | "SELL"
  buy_range: [number, number]
  position_pct: number
  size_shares?: number
  size_amount?: number
  stop_loss: number
  target: number
  holding_days: string
  reason: string
  confidence?: "高" | "中" | "低"
  urgency?: string
  risk_notes?: string[]
}

export interface StockPerformance {
  symbol: string
  name: string
  entry_price: number
  current_price: number
  pnl_pct: number
  pnl_amount: number
}

export interface PostMarketData {
  total_pnl_pct: number
  total_pnl_amount: number
  stocks: StockPerformance[]
  next_day_plan: string
}

export interface Message {
  id: string
  type: MessageType
  title: string
  summary: string
  content: string
  created_at: string
  read: boolean
  priority: "high" | "medium" | "low"
  /** Structured data for late_session messages */
  stock_recommendations?: StockRecommendation[]
  /** Structured data for post_market messages */
  post_market_data?: PostMarketData
}

export interface MessageListResponse {
  items: Message[]
  messages: Message[] // v36.0 compat alias
  count: number
  total: number // v36.0 compat alias
  page: number
  per_page: number
  has_more: boolean
  unread_count: number
}

export type DataFreshness = "realtime" | "delayed" | "stale"

// v36.0 watchlist types
export interface WatchlistStock {
  symbol: string
  name: string
  price: number | null
  pct_change: number | null
  ai_attitude: "bullish" | "neutral" | "cautious"
  ai_attitude_label: string
  latest_message_summary?: string
}

// v36.0 performance types
export interface PerformanceSummary {
  accuracy_pct: number
  total_signals: number
  profitable_signals: number
  recent_results: PerformanceResult[]
}

export interface PerformanceResult {
  id: number
  symbol: string
  name: string
  action: string
  return_pct: number
  decided_at: string
}
