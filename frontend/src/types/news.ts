/** News and anomaly types for v2.0. */

export interface StockNewsItem {
  title: string
  content: string
  datetime: string
  source: string
  url: string
  sentiment?: "positive" | "negative" | "neutral"
  impact_level?: "high" | "medium" | "low"
}

export interface AnomalyItem {
  datetime: string
  symbol: string
  name: string
  change_type: string
  description: string
  sector?: string
}

export interface SentimentSummary {
  symbol: string
  overall: "positive" | "negative" | "neutral"
  positive_count: number
  negative_count: number
  neutral_count: number
  total_count: number
  score: number
  summary: string | null
}

export interface HotRankItem {
  rank: number
  symbol: string
  name: string
  price: number | null
  pct_change: number | null
}
