/** v20.0 Market Intelligence types — mirrors backend schemas. */

// ─── Enums ───────────────────────────────────────────────────────────────────

export type SignalType =
  | "S1_TREND"
  | "S2_MOMENTUM_SHIFT"
  | "S3_SENTIMENT"
  | "S4_ANOMALY"
  | "S5_VOLATILITY"
  | "S6_CORRELATION_SHIFT"
  | "S7_POLICY_DRIVEN"
  | "S8_MACRO_DRIVEN"
  | "S9_REGIME_CHANGE"
  | "STOCK_ALERT"
  | "SYSTEM_ALERT"

export type RiskLevel = "LOW" | "MODERATE" | "ELEVATED" | "EXTREME"

export type MarketPhase =
  | "PRE_OPEN"
  | "CALL_AUCTION"
  | "MORNING"
  | "MIDDAY_BREAK"
  | "AFTERNOON"
  | "CLOSING_AUCTION"
  | "POST_CLOSE"
  | "CLOSED"

export type PushDecision = "URGENT" | "DIGEST" | "BLOCK" | "SUPPRESS"

// ─── Signal Models ───────────────────────────────────────────────────────────

export interface SourceReference {
  source_id: string
  provider: string
  data_type: string
  timestamp: string
  reliability_score: number
}

export interface RiskContext {
  volatility_regime: string
  circuit_breaker_state: string
  var_1d_95: number | null
  concentration_risk: number | null
  macro_regime: string
  explanation: string
  watch_items: string[]
}

export interface MarketSignal {
  signal_id: string
  signal_type: SignalType
  timestamp: string
  assets: string[]
  phase: MarketPhase
  confidence_score: number
  risk_level: RiskLevel
  risk_context: RiskContext | null
  sources: SourceReference[]
  producer: string
  summary_short: string
  summary_detailed: string | null
  confirmed: boolean
  confirmation_sources: string[]
  is_injection: boolean
  injection_reason: string | null
  source_reliability_score: number
  data_freshness_ms: number
  lineage_node_id: string | null
}

// ─── Radar Responses ─────────────────────────────────────────────────────────

export interface TrendItem {
  asset: string
  signal_count: number
  latest_signal: MarketSignal
  types: string[]
}

export interface TrendRadarResponse {
  trends: TrendItem[]
  timestamp: string
}

export interface AnomalyRadarResponse {
  anomalies: MarketSignal[]
  timestamp: string
}

// ─── Sector Rotation ─────────────────────────────────────────────────────────

export interface SectorData {
  name: string
  performance: number
  volume_change: number
  signal_count: number
  status: string
}

export interface SectorRotationResponse {
  sectors: SectorData[]
  rotation_direction: string
  leading: string[]
  lagging: string[]
  error?: string
}

// ─── Correlation ─────────────────────────────────────────────────────────────

export interface CorrelationResponse {
  matrix: Record<string, Record<string, number>>
  error?: string
}

// ─── Macro Regime ────────────────────────────────────────────────────────────

export interface MacroRegimeResponse {
  regime: string
  confidence: number
  indicators: Record<string, number | string>
  explanation: string
  error?: string
}

// ─── Timeline ────────────────────────────────────────────────────────────────

export interface TimelineEntry {
  signal_id: string
  signal_type: SignalType
  timestamp: string
  phase: MarketPhase
  summary_short: string
  risk_level: RiskLevel
  push_decision: PushDecision
  assets: string[]
}

// ─── Signal Accuracy ─────────────────────────────────────────────────────────

export interface SignalAccuracyResponse {
  accuracy: Record<string, number>
  error?: string
}

export interface AccuracyHistoryPoint {
  date: string
  accuracy_t3: number | null
  accuracy_t5: number | null
  sample_count: number
}

export interface AccuracyHistoryResponse {
  data: AccuracyHistoryPoint[]
  signal_type: string
  granularity: string
  window_days: number
  error?: string
}

// ─── User Config ─────────────────────────────────────────────────────────────

export interface UserFollows {
  stocks: string[]
  sectors: string[]
  concepts: string[]
  signal_types: string[]
  risk_levels: string[]
  keywords: string[]
  indices: string[]
  macro_factors: string[]
}

export interface NotificationPrefs {
  quiet_hours_start: string
  quiet_hours_end: string
  max_daily_notifications: number
  digest_interval_minutes: number
  enabled_channels: string[]
  min_confidence_threshold: number
  diversity_level: string
}

// ─── Display Helpers ─────────────────────────────────────────────────────────

export const SIGNAL_TYPE_LABELS: Record<SignalType, string> = {
  S1_TREND: "趋势",
  S2_MOMENTUM_SHIFT: "动量",
  S3_SENTIMENT: "舆情",
  S4_ANOMALY: "异动",
  S5_VOLATILITY: "波动",
  S6_CORRELATION_SHIFT: "相关性",
  S7_POLICY_DRIVEN: "政策",
  S8_MACRO_DRIVEN: "宏观",
  S9_REGIME_CHANGE: "体制",
  STOCK_ALERT: "个股",
  SYSTEM_ALERT: "系统",
}

export const RISK_LEVEL_LABELS: Record<RiskLevel, string> = {
  LOW: "低",
  MODERATE: "中",
  ELEVATED: "高",
  EXTREME: "极端",
}

export const MARKET_PHASE_LABELS: Record<MarketPhase, string> = {
  PRE_OPEN: "盘前",
  CALL_AUCTION: "集合竞价",
  MORNING: "上午盘",
  MIDDAY_BREAK: "午间休市",
  AFTERNOON: "下午盘",
  CLOSING_AUCTION: "尾盘竞价",
  POST_CLOSE: "盘后",
  CLOSED: "休市",
}
