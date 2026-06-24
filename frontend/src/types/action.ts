export interface ActionItem {
  id: string
  symbol: string
  stock_name: string
  action: "buy" | "sell" | "reduce" | "hold"
  urgency: "immediate" | "today" | "observe"
  session?: string
  confidence: number
  thesis_id?: string
  execution_plan: ExecutionPlan
  status: "pending" | "confirmed" | "executed" | "rejected" | "expired"
  created_at: string
}

export interface ExecutionPlan {
  time_window: string
  target_shares: number
  target_pct: number
  price_guidance: string
  stop_loss: number
  stop_loss_pct: number
  price_target: number
  thesis_summary: string
  confidence: number
  key_risk: string
  contingencies: string[]
  invalidation: string
}

export interface RegimeState {
  sentiment: {
    phase: string
    phase_cn: string
    position_limits: { max_position_pct: number; max_equity_pct: number }
  }
  hmm: { state: string; probability: number }
  risk_budget: { daily_limit_pct: number; used_pct: number; remaining_pct: number }
}

export interface BootstrapData {
  portfolio: import("./portfolio").Portfolio
  action_queue: ActionItem[]
  unread_count: number
  regime: RegimeState
  recent_messages: MessageSummary[]
  market_status: string
}

export interface MessageSummary {
  id: string
  type: string
  title: string
  created_at: string
}

export interface Thesis {
  id: string
  symbol: string
  stock_name: string
  narrative: string
  current_confidence: number
  status: "active" | "weakening" | "invalidated" | "realized"
  expires_at: string
  invalidation_condition: string
  created_at: string
}

export interface ReviewData {
  date: string
  daily_pnl: number
  daily_pnl_pct: number
  decisions: DecisionOutcome[]
  signal_accuracy_30d: number
  brier_score: number
  missed_opportunities: MissedOpportunity[]
  ai_summary: string
}

export interface DecisionOutcome {
  id: string
  symbol: string
  stock_name: string
  action: string
  result: "correct" | "wrong" | "pending"
  pnl: number | null
  reason: string
}

export interface MissedOpportunity {
  symbol: string
  stock_name: string
  description: string
  potential_pnl_pct: number
}
