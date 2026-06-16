/** Portfolio types for FR-PF001 ~ PF003. */

export type BoardType = "main" | "chinext" | "star"

export interface Position {
  id: string
  symbol: string
  name: string
  board: BoardType
  costPrice: number
  shares: number
  buyDate: string
  note?: string
}

export interface Portfolio {
  version: 1
  updatedAt: string
  positions: Position[]
}

export interface PositionWithPnL extends Position {
  currentPrice: number | null
  todayPctChange: number | null
  marketValue: number
  pnl: number
  pnlPercent: number
}

export interface PortfolioSummary {
  positionCount: number
  totalCost: number
  totalMarketValue: number
  totalPnL: number
  totalPnLPercent: number
  positions: PositionWithPnL[]
}

export interface PositionAdvice {
  symbol: string
  name: string
  action: string
  reason: string
  target_price: number | null
}

export interface ConcentrationRisk {
  level: "low" | "medium" | "high"
  description: string
  top_holdings_pct: number | null
}

export interface PortfolioDiagnosis {
  status: string
  health_score: number
  health_label: string
  summary: string
  concentration_risk: ConcentrationRisk | null
  position_advice: PositionAdvice[]
  rebalancing: string[]
  risk_warnings: string[]
  reasoning: string[]
  generated_at: string | null
  model_used: string | null
  message?: string
}
