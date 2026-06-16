/** Sentiment analysis and cross-market types — PRD v3.2 FR-TN003~005, FR-GM004 */

// FR-TN003: Resonance events
export interface ResonanceTimelineEntry {
  platform: string
  rank: number
  timestamp: string
}

export interface ResonanceEvent {
  event_id: string
  title: string
  resonance_level: string // "L1" | "L2" | "L3"
  platforms: string[]
  rank_timeline: ResonanceTimelineEntry[]
  related_stocks: string[]
  sentiment: string // "positive" | "negative" | "mixed" | "neutral"
  first_appeared: string
  last_updated: string
  heat_score: number
}

export interface ResonanceResult {
  status: string
  events: ResonanceEvent[]
  total: number
  generated_at: string
}

// FR-TN004: Sentiment report
export interface SentimentCoreTrend {
  topic: string
  resonance_level: string
  sentiment: string
  related_stocks: string[]
  summary: string
}

export interface SentimentPolicySignal {
  title: string
  impact: string
  affected_sectors: string[]
  confidence: number
  summary: string
}

export interface SentimentGlobalLinkage {
  us_market_summary: string
  commodity_impact: string
  forex_impact: string
}

export interface SentimentRiskAlert {
  type: string
  title: string
  severity: string // "low" | "medium" | "high"
  mitigation: string
}

export interface SentimentSectorOutlook {
  bullish: string[]
  bearish: string[]
  neutral: string[]
}

export interface SentimentReport {
  status: string
  core_trends: SentimentCoreTrend[]
  policy_signals: SentimentPolicySignal[]
  global_linkage: SentimentGlobalLinkage
  risk_alerts: SentimentRiskAlert[]
  sector_outlook: SentimentSectorOutlook
  overall_outlook: string
  generated_at?: string
  disclaimer?: string
  message?: string
}

// FR-TN005: Market pulse
export interface HoldingsNewsItem {
  title: string
  platform: string
  heat_score: number
  sentiment: string
}

export interface MarketPulseResult {
  status: string
  hot_events: ResonanceEvent[]
  holdings_news: Record<string, HoldingsNewsItem[]>
  global_snapshot: {
    indices: { name: string; pct_change: number | null }[]
    commodities: { name: string; pct_change: number | null }[]
    currencies: { name: string; price: number | null }[]
  } | null
  generated_at: string
}

// FR-GM004: Cross-market
export interface CrossMarketPeer {
  symbol: string
  price: number | null
  pct_change: number | null
}

export interface CrossMarketGroup {
  trend: string
  peers: CrossMarketPeer[]
  impact_score: number
  avg_pct_change?: number
  summary?: string
}

export interface CrossMarketResult {
  symbol: string
  tags: string[]
  us_market: CrossMarketGroup
  hk_market: CrossMarketGroup
  commodity_exposure: CrossMarketGroup
  global_indices: CrossMarketGroup
  combined_impact_score: number
  impact_direction: string
  generated_at: string
}
