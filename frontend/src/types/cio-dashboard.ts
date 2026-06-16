/** v34.0 CIO Dashboard & Intelligence Agent types */

export interface MacroProfile {
  symbol: string
  name: string
  sector: string
  macro_score: number
  rotation_signal: "hold" | "reduce" | "exit" | "add"
  rotation_reason: string
  top_factor: string
  macro_sensitivities: Record<string, number>
}

export interface ConstraintAlert {
  symbol: string
  name: string
  violations: string[]
}

export interface DashboardData {
  portfolio: {
    position_count: number
    profiles: MacroProfile[]
    macro_exposure: Record<string, number>
    stressed_count: number
    stressed_symbols: string[]
  }
  black_swan: {
    alert_level: string
    message?: string
  }
  constraint_alerts?: ConstraintAlert[]
}

export interface DebateArgument {
  perspective: "bull" | "bear"
  claim: string
  source: string
  strength: number
  confidence: number
}

export interface DebateVerdict {
  action: string
  conviction: string
  win_probability: number
  risk_reward_ratio: number | null
  stop_loss_pct: number | null
  reasoning: string
}

export interface DebateRecord {
  symbol: string
  name: string
  trigger: string
  bull_arguments: DebateArgument[]
  bear_arguments: DebateArgument[]
  bull_score: number
  bear_score: number
  verdict: DebateVerdict
  risk_veto: boolean
  final_action: string
  timestamp: string
}

export interface RotationPlan {
  sell_symbol: string
  sell_name: string
  sell_reason: string
  buy_candidates: {
    symbol: string
    name: string
    sector: string
    score: number
  }[]
  blocked_candidates: {
    symbol: string
    name: string
    reason: string
  }[]
  risk_notes: string[]
}

export interface ImpactChainResult {
  event: string
  chains: {
    chain_id: string
    trigger_event: string
    trigger_type: string
    transmission_paths: {
      cause: string
      effect: string
      direction: string
      magnitude: string
      affected_sectors: string[]
      lag: string
    }[]
  }[]
  affected_sectors: string[]
}

export interface EquitySnapshot {
  date: string
  total_value: number
  total_cost: number
  unrealized_pnl: number
  position_count: number
}

export interface ChecklistResult {
  symbol: string
  overall_passed: boolean
  checks: {
    name: string
    severity: string
    finding: string
    passed: boolean
  }[]
}
