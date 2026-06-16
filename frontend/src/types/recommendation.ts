/** Types for v28.0 Smart Stock Recommendation system. */

export interface Recommendation {
  id: string
  symbol: string
  name: string
  action: string
  style: string
  session: string
  score: number
  confidence: "high" | "medium" | "low"
  reason: string
  risk_notes: string
  entry_price: number | null
  target_price: number | null
  stop_loss: number | null
  factors: Record<string, number>
  created_at: string
  status: string
  ai_analyzed?: boolean
  sector?: string
  is_cross_sector?: boolean
  outcomes?: RecommendationOutcome
  sub_scores?: Record<string, number> | null
  current_price?: number | null
  current_pct_change?: number | null
  price_vs_entry?: number | null
  market_open?: boolean
}

export interface RecommendationOutcome {
  rec_id: string
  entry_price: number | null
  actual_price_t1: number | null
  actual_change_t1: number | null
  correct_t1: number | null
  actual_price_t3: number | null
  actual_change_t3: number | null
  correct_t3: number | null
  actual_price_t5: number | null
  actual_change_t5: number | null
  correct_t5: number | null
  actual_price_t10: number | null
  actual_change_t10: number | null
  correct_t10: number | null
  backfilled_at: string | null
}

export interface RecommendationListResponse {
  items: Recommendation[]
  count: number
}

export interface InvestmentStyle {
  key: string
  label: string
}

export interface StylesResponse {
  styles: InvestmentStyle[]
}

export interface PreferencesResponse {
  investment_style: string
}

export interface InvestmentStyleConfig {
  styles: string[]
  sector_preferences: string[]
  blacklist: string[]
  session_toggles: Record<string, boolean>
}

export interface WindowStats {
  filled: number
  wins: number
  win_rate: number | null
  avg_return: number | null
}

export interface PerformanceStats {
  total_recs: number
  windows: {
    t1: WindowStats
    t3: WindowStats
    t5: WindowStats
    t10: WindowStats
  }
}

export interface RefreshResponse {
  status: "ok" | "accepted" | "cooldown" | "skipped"
  message?: string
  session?: string
  total?: number
  retry_after?: number
  run_id?: string
}

export interface StyleDetail {
  status: string | null
  reason: string | null
  count: string | null
}

export interface RefreshRunStatus {
  run_id?: string
  status: "running" | "completed" | "failed" | "unknown"
  session?: string
  total_recs?: number | null
  error?: string | null
  style_details?: Record<string, StyleDetail>
}
