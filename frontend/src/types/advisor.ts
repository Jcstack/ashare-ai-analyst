/** AI Trading Advisor types — PRD v3.2 FR-TA001~004, FR-HS003~004 */

export interface QuantSignals {
  technical_score: number
  momentum_score: number
  strategy_consensus: string
  bayesian_probability: number
}

export interface TargetPrice {
  low: number
  high: number
}

export interface StockAdvice {
  status: string
  symbol: string
  name: string
  action: string
  action_label: string
  confidence: number
  risk_level: string
  quant_signals: QuantSignals
  ai_reasoning: string[]
  risk_warnings: string[]
  target_price: TargetPrice | null
  stop_loss: number | null
  disclaimer: string
  generated_at: string
  model_used?: string
  message?: string
}

export interface WatchlistStrategyItem {
  symbol: string
  name: string
  action: string
  action_label: string
  confidence: number
  risk_level: string
  ai_reasoning: string[]
}

export interface WatchlistStrategyResult {
  status: string
  items: WatchlistStrategyItem[]
  total: number
  generated_at: string
  disclaimer: string
}

export interface PositionAdvice {
  symbol: string
  name: string
  action: string
  action_label: string
  confidence: number
  risk_level: string
  cost_price: number
  current_price: number
  pnl_pct: number
  shares: number
  holding_days: number
  ai_reasoning: string[]
  risk_warnings: string[]
  stop_loss: number | null
}

export interface PortfolioAdviceResult {
  status: string
  positions: PositionAdvice[]
  total: number
  generated_at: string
  disclaimer: string
}

export interface HolidayImpactFactor {
  name: string
  impact: string
  weight: number
  description: string
}

export interface HolidayImpactResult {
  status: string
  symbol: string
  impact_score: number
  impact_direction: string
  factors: HolidayImpactFactor[]
  ai_assessment: string
  suggested_action: string
  confidence: number
  generated_at: string
  disclaimer: string
}

export interface PositionImpact {
  symbol: string
  impact: string
  brief: string
}

export interface ReopenBriefingResult {
  status: string
  market_outlook: string
  confidence: number
  summary: string
  key_events: string[]
  position_impacts: PositionImpact[]
  recommendations: string[]
  risk_warnings: string[]
  generated_at: string
  disclaimer: string
}
