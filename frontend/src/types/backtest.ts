export interface StrategyInfo {
  key: string
  name: string
}

export interface BacktestRequest {
  symbol: string
  strategy: string
  board: string
}

export interface BacktestResponse {
  status: string
  symbol?: string
  strategy_key?: string
  strategy_name?: string
  board?: string
  metrics?: Record<string, number | string | null>
  report?: string
  trades_count?: number
  equity_curve?: number[]
  initial_capital?: number
  final_capital?: number
  message?: string
}

export interface BacktestInterpretRequest {
  symbol: string
  strategy_name: string
  metrics: Record<string, number | string | null>
  trades_count?: number
  initial_capital?: number
  final_capital?: number
}

export interface BacktestInterpretResult {
  status: string
  summary: string
  strategy_explain: string
  strengths: string[]
  weaknesses: string[]
  improvement_suggestions: string[]
  risk_analysis: string
  beginner_tips: string
  message?: string
}

// v3.0 Strategy Lab types

export interface StrategyFlowStep {
  id: string
  label: string
  type: string
  description: string
}

export interface StrategyFlowEdge {
  source: string
  target: string
  label: string
}

export interface StrategyParam {
  key: string
  label: string
  type: string
  min: number
  max: number
  step: number
  default: number
  current: number
}

export interface StrategyMetadata {
  status: string
  name: string
  description: string
  flow_steps: StrategyFlowStep[]
  flow_edges: StrategyFlowEdge[]
  configurable_params: StrategyParam[]
}

export interface TradeSignalItem {
  date: string
  signal: number
  strength: number
  reason: string
  close_price: number
}

export interface RoundTripItem {
  buy_date: string
  sell_date: string
  buy_price: number
  sell_price: number
  shares: number
  pnl: number
  pnl_pct: number
  holding_days: number
  buy_reason: string
  sell_reason: string
}

export interface AttributionData {
  monthly_pnl: Record<string, number>
  signal_distribution: { buy: number; sell: number; hold: number }
  monthly_win_rates: Record<string, number>
}

export interface BacktestRequestV2 {
  symbol: string
  strategy: string
  board: string
  param_overrides?: Record<string, number>
}

export interface BacktestResponseV2 {
  status: string
  symbol?: string
  strategy_key?: string
  strategy_name?: string
  board?: string
  metrics?: Record<string, number | string | null>
  report?: string
  trades_count?: number
  equity_curve?: number[]
  initial_capital?: number
  final_capital?: number
  signals?: TradeSignalItem[]
  round_trips?: RoundTripItem[]
  dates?: string[]
  attribution?: AttributionData
  strategy_metadata?: StrategyMetadata
  message?: string
}

export interface NLStrategyRequest {
  description: string
  symbol?: string
}

export interface NLStrategyResult {
  status: string
  strategy_key: string
  params: Record<string, number>
  explanation: string
  confidence: number
  message?: string
}

export interface AIOptimizationRequest {
  symbol: string
  strategy_key: string
  current_params: Record<string, number>
  current_metrics: Record<string, number>
}

export interface AIOptimizationResult {
  status: string
  suggested_params: Record<string, number>
  reasoning: string[]
  param_explanations: Record<string, string>
  message?: string
}

export interface AIAttributionRequest {
  symbol: string
  strategy_name: string
  round_trips: RoundTripItem[]
  metrics: Record<string, number>
}

export interface AIAttributionResult {
  status: string
  summary: string
  key_findings: string[]
  win_factors: string[]
  loss_factors: string[]
  improvement_suggestions: string[]
  risk_assessment: string
  message?: string
}

export interface LatestSignalItem {
  symbol: string
  strategy_key: string
  strategy_name: string
  signal: "buy" | "sell" | "hold"
  signal_value: number
  strength: number
  reason: string
}

export interface PaperPosition {
  id: string
  symbol: string
  name: string
  strategy_key: string
  entry_price: number
  shares: number
  entry_date: string
}

export interface PaperClosedTrade {
  id: string
  symbol: string
  name: string
  strategy_key: string
  entry_price: number
  exit_price: number
  shares: number
  entry_date: string
  exit_date: string
  pnl: number
  pnl_pct: number
}

export interface PaperPortfolio {
  version: number
  updatedAt: string
  initial_capital: number
  cash: number
  positions: PaperPosition[]
  closed_trades: PaperClosedTrade[]
}
