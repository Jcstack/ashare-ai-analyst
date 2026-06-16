/** Intel Report types for v25.0 Intel-Portfolio Analysis. */

export interface ReportFactor {
  category: string
  impact: string
  weight: number
  description: string
}

export interface ReportPositionContext {
  cost_price: number | null
  shares: number | null
  pnl_percent: number | null
  advice: string
  key_levels: { support: number; resistance: number } | null
}

export interface AffectedSectors {
  bullish?: Array<{ sector: string; logic: string }>
  bearish?: Array<{ sector: string; logic: string }>
  neutral?: Array<{ sector: string; logic: string }>
}

export interface IntelReport {
  id: string
  symbol: string
  stock_name: string
  intel_item_ids: string[]
  refresh_cycle: string
  action: "buy" | "sell" | "hold" | "watch"
  signal: "bullish" | "bearish" | "neutral"
  confidence: number
  summary: string
  factors: ReportFactor[]
  position_context: ReportPositionContext | null
  risk_warnings: string[]
  outlook: string
  reasoning: string[]
  intel_summary: string
  model_used: string
  generated_at: string
  created_at: string
  thread_id: string | null
  is_read: boolean
  is_macro: boolean
  affected_sectors?: AffectedSectors
}

export interface ReportListResponse {
  reports: IntelReport[]
  total: number
}

export interface ReportListParams {
  symbol?: string
  unread_only?: boolean
  limit?: number
  offset?: number
  macro_only?: boolean
}
