/** AI Agent types for v2.0 intelligent advisor features. */

// ─── v8.0 Unified Analysis Types ────────────────────────────────────────────

export interface DimensionAnalysis {
  key: string
  label: string
  signal: "bullish" | "neutral" | "bearish"
  score: number
  reasoning: string
}

export interface UnifiedConfidence {
  score: number
  label: string
  basis: string[]
}

export interface UnifiedRiskWarning {
  type: string
  description: string
  data_reference?: string
}

export interface UnifiedDataReference {
  field: string
  value: string
  source: string
}

/** Data lineage reference — tracks where data came from. */
export interface DataLineageRef {
  source: string
  field: string
  timestamp?: string
  agent?: string
}

/** Scenario option — one of bullish/base/bearish outcomes. */
export interface ScenarioOption {
  name: string
  probability: number
  description: string
  target_price?: number
  risk_level?: "low" | "medium" | "high"
  key_drivers?: string[]
}

export interface UnifiedAnalysis {
  status: string
  symbol: string
  action: string
  action_label: string
  confidence: UnifiedConfidence
  risk_level: string
  summary: string
  dimensions: DimensionAnalysis[]
  risk_warnings: UnifiedRiskWarning[]
  target_price: { low: number; high: number } | null
  stop_loss: number | null
  contrarian_check: string
  data_references: UnifiedDataReference[]
  disclaimer: string
  model_used: string
  generated_at: string
  message?: string
  // Five-element output (agent spec compliance)
  key_assumptions?: string[]
  failure_modes?: string[]
  data_lineage?: DataLineageRef[]
  data_gaps?: string[]
  scenarios?: ScenarioOption[]
  // Evaluation quality score (WS5)
  evaluation?: {
    quality_score: number
    checks_passed: number
    checks_total: number
    flags?: string[]
  }
  // backward compat
  trend: string
  signal: string
  confidence_number: number
  reasoning: string[]
  quant_signals: Record<string, number | string>
  ai_reasoning: string[]
}

// ─── v11.0 Conversation Types ─────────────────────────────────────────────

export interface ConversationMessage {
  role: "user" | "assistant"
  content: string
  timestamp: string
}

export interface ConversationResponse {
  status: string
  session_id: string
  symbol: string
  analysis: UnifiedAnalysis | null
  messages: ConversationMessage[]
  suggested_questions: string[]
  generated_at: string
  model_used: string
  disclaimer: string
  message?: string
}

// ─── Legacy Types ───────────────────────────────────────────────────────────

export interface AIAnalysisResult {
  status: string
  symbol: string
  trend: "bullish" | "bearish" | "neutral"
  signal: "buy" | "sell" | "hold" | "watch"
  confidence: number
  risk_level: "low" | "medium" | "high"
  reasoning: string[]
  target_price_range: { low: number; high: number } | null
  key_factors: string[]
  risk_warnings: string[]
  news_sentiment: string | null
  generated_at: string | null
  model_used: string | null
  message: string | null
}

export interface QuickInsight {
  symbol: string
  signal: "bullish" | "bearish" | "neutral"
  confidence: number
  summary: string
  risk_badge: "low" | "medium" | "high"
  generated_at: string | null
}

export interface Alert {
  id: string
  symbol: string
  name: string
  alert_type: string
  severity: "critical" | "warning" | "info"
  title: string
  description: string
  value: number | null
  threshold: number | null
  timestamp: string
}

export interface MarketAIOverview {
  status: string
  market_trend: "bullish" | "bearish" | "neutral"
  risk_assessment: "low" | "medium" | "high"
  summary: string
  key_points: string[]
  sector_outlook: { leading: string[]; lagging: string[] } | null
  generated_at: string | null
}

/** Move (rise/fall) attribution analysis — PRD v2.2 FR-PI001/PI002. */

export interface MoveAnalysisFactor {
  category: "market" | "sector" | "news" | "technical" | "flow" | "sentiment"
  impact: "positive" | "negative" | "neutral"
  weight: number
  description: string
}

export interface MoveAnalysisPositionContext {
  cost_price: number | null
  current_price: number | null
  pnl_percent: number | null
  holding_days: number | null
  advice: string
  key_levels: { support: number; resistance: number } | null
}

export interface MoveAnalysis {
  status: string
  symbol: string
  name: string
  analysis_date: string
  price_change: number | null
  move_summary: string
  factors: MoveAnalysisFactor[]
  position_context: MoveAnalysisPositionContext | null
  outlook: string
  reasoning: string[]
  generated_at: string | null
  model_used: string | null
  message: string | null
}

// ─── v34.0 Investment Agent (OODA) Types ──────────────────────────────────────

export interface InvestmentThesis {
  symbol: string
  name: string
  direction: string
  conviction: number
  thesis_text: string
  status: string
  updated_at: string
  sector: string
}

export interface DecisionOutcome {
  decision_id: string
  symbol: string
  action: string
  decided_at: string
  decided_price: number
  t1_return_pct: number | null
  t3_return_pct: number | null
  t5_return_pct: number | null
  direction_correct: boolean | null
}

export interface AccuracyStats {
  direction_accuracy: number
  avg_t1_return: number
  avg_t3_return: number
  avg_t5_return: number
  total_decisions: number
  profitable_decisions: number
}

export interface AgentStatus {
  active_theses: number
  theses: InvestmentThesis[]
  accuracy: AccuracyStats
  recent_decisions: DecisionOutcome[]
}

export interface CycleResult {
  cycle_id: string
  signals_processed: number
  proposals_generated: Record<string, unknown>[]
}

export interface CalibrationActionStats {
  total: number
  evaluated: number
  accuracy: number | null
  avg_t1_return: number | null
  avg_t3_return: number | null
}

export interface CalibrationReport {
  status: string
  lookback_days: number
  total_decisions: number
  evaluated_decisions: number
  overall_accuracy: number | null
  avg_returns: { t1: number | null; t3: number | null; t5: number | null }
  by_action: Record<string, CalibrationActionStats>
  calibration_active: boolean
}
