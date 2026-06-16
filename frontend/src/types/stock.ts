export interface WatchlistItem {
  symbol: string
  name: string
  board: string
  close: number | null
  open: number | null
  high: number | null
  low: number | null
  change: number | null
  pct_change: number | null
  volume: number | null
  date: string | null
}

export interface StockDetail {
  symbol: string
  name: string
  board: string
  close: number | null
  open: number | null
  high: number | null
  low: number | null
  change: number | null
  pct_change: number | null
  volume: number | null
  date: string | null
}

export interface OHLCVRecord {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface IndicatorsSummary {
  values: Record<string, number | null>
}

export interface IndicatorsFullRecord {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  indicators: Record<string, number | null>
}

export interface PatternDetection {
  name: string
  value: number
}

export interface SupportResistanceLevel {
  level: number
  type: string
  touches: number
}

export interface IntradayTradesStats {
  buy_volume: number
  sell_volume: number
  neutral_volume: number
  total_volume: number
  buy_ratio: number
  sell_ratio: number
  is_historical?: boolean
}

export interface TickRecord {
  time: string
  price: number
  volume: number
  change: number | null
  direction: "buy" | "sell" | "neutral"
}

export interface IntradayTradesSnapshot {
  stats: IntradayTradesStats
  recent_ticks: TickRecord[]
  is_historical?: boolean
}

export interface QuoteSnapshot {
  price: number | null
  change: number | null
  pct_change: number | null
  volume: number | null
  open: number | null
  high: number | null
  low: number | null
  prev_close: number | null
  amount: number | null
}

export interface FundFlowSnapshot {
  date: string
  main_net: number | null
  super_large_net: number | null
  large_net: number | null
  medium_net: number | null
  small_net: number | null
}

export interface FundFlowDetailSnapshot {
  inflow: number | null
  outflow: number | null
  net: number | null
}

export interface RealtimeSnapshot {
  symbol: string
  timestamp: string
  quote: QuoteSnapshot | null
  trades: IntradayTradesSnapshot | null
  fund_flow: FundFlowSnapshot | null
  fund_flow_detail: FundFlowDetailSnapshot | null
}
