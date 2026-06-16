export interface PredictionResult {
  status: string
  symbol?: string
  trend?: string
  signal?: string
  confidence?: number
  risk_level?: string
  reasoning?: string
  target_price_range?: number[]
  key_factors?: string[]
  risk_warnings?: string[]
  message?: string
}

export interface EnhancedPredictionResult extends PredictionResult {
  data_sources?: string[]
  generated_at?: string
}

export interface ComparisonPredictionResult {
  status: string
  analyses: EnhancedPredictionResult[]
  comparison_summary?: string
  recommendation_order?: string[]
  message?: string
  generated_at?: string
}

export type DataSource =
  | "indicators"
  | "dragon_tiger"
  | "fund_flow"
  | "bayesian"
  | "risk"
  | "news"

export const DATA_SOURCE_LABELS: Record<DataSource, string> = {
  indicators: "技术指标",
  dragon_tiger: "龙虎榜",
  fund_flow: "资金流向",
  bayesian: "贝叶斯分析",
  risk: "风控模型",
  news: "新闻舆情",
}
