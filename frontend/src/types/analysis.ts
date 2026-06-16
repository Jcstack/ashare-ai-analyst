// Bayesian indicator analysis types

export interface IndicatorProbabilities {
  up: number
  flat: number
  down: number
}

export interface BayesianIndicatorItem {
  indicator: string
  current_value: number
  bin_label: string
  probabilities: IndicatorProbabilities
  sample_count: number
  interpretation: string
  analogy: string
  data_sufficient: boolean
}

export interface BayesianComposite {
  signal: string
  bullish_count: number
  bearish_count: number
  neutral_count: number
  summary: string
}

export interface BayesianAnalysisResult {
  symbol: string
  name: string
  analysis_date: string
  lookback_days: number
  forward_days: number
  indicators: BayesianIndicatorItem[]
  composite: BayesianComposite
}

// Dragon Tiger deep types

export interface DragonTigerSeatItem {
  seat_name: string
  seat_type: string
  buy_amount: number | null
  sell_amount: number | null
  net_amount: number | null
}

export interface DragonTigerStockStats {
  appearances_3m: number
  institution_net_buy: number
  avg_return_5d: number
  win_rate_5d: number
}

export interface DragonTigerAIResult {
  status: string
  symbol: string
  summary: string
  signal: string
  confidence: number
  key_findings: string[]
  risk_factors: string[]
  historical_performance: DragonTigerStockStats | null
  reasoning: string[]
  generated_at: string | null
  model_used: string | null
  message: string | null
}

// Chart events

export interface ChartEvent {
  date: string
  type: "news" | "dragon_tiger" | "pattern" | "anomaly"
  title: string
  impact: "positive" | "negative" | "neutral"
  details: string
  url?: string
}

export interface ChartEventsResult {
  symbol: string
  events: ChartEvent[]
}
