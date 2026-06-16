export interface MarketIndex {
  name: string
  code: string
  price: number
  change: number
  pct_change: number
}

export interface RealtimeQuote {
  symbol: string
  name: string
  price: number | null
  change: number | null
  pct_change: number | null
  open: number | null
  high: number | null
  low: number | null
  prev_close: number | null
  volume: number | null
  amount: number | null
}

export interface DragonTigerItem {
  rank: number | null
  symbol: string
  name: string
  date: string | null
  reason: string | null
  close: number | null
  pct_change: number | null
  net_buy: number | null
  buy_amount: number | null
  sell_amount: number | null
  total_amount: number | null
  turnover: number | null
  float_mv: number | null
}

export interface GlobalIndexItem {
  symbol: string
  name: string
  region: string
  price: number | null
  change: number | null
  pct_change: number | null
  prev_close: number | null
}

export interface GlobalCommodityItem {
  symbol: string
  name: string
  unit: string
  price: number | null
  change: number | null
  pct_change: number | null
}

export interface GlobalCurrencyItem {
  symbol: string
  name: string
  price: number | null
  change: number | null
  pct_change: number | null
}

export interface GlobalMarketSnapshot {
  indices: GlobalIndexItem[]
  commodities: GlobalCommodityItem[]
  currencies: GlobalCurrencyItem[]
}

export interface TradingCalendarInfo {
  date: string
  is_trading_day: boolean
  current_session: string
  next_trading_day: string
  is_holiday_period: boolean
  holiday_name: string | null
  holiday_end_date: string | null
  days_until_open: number
  is_emergency_closure: boolean
}

export interface MarketStatusNextEvent {
  type: string
  time: string
  countdown_seconds: number
}

export interface MarketStatusHolidayInfo {
  name: string
  end_date: string
  days_remaining: number
}

export interface MarketStatus {
  status: "trading" | "closed" | "holiday" | "lunch" | "pre_market" | "emergency"
  label: string
  is_trading: boolean
  next_event: MarketStatusNextEvent
  holiday_info: MarketStatusHolidayInfo | null
  is_emergency: boolean
  emergency_reason: string | null
}

export interface LimitUpItem {
  rank: number | null
  symbol: string
  name: string
  pct_change: number | null
  price: number | null
  amount: number | null
  float_mv: number | null
  total_mv: number | null
  turnover: number | null
  seal_amount: number | null
  first_seal_time: string | null
  last_seal_time: string | null
  break_count: number | null
  consecutive: number | null
  industry: string | null
}
