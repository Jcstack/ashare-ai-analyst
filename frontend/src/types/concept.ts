/** Concept sector types — PRD v3.3 FR-CS001~007 */

// Concept heat ranking
export interface ConceptLeader {
  symbol: string
  name: string
  pct_change: number
}

export interface ConceptHeatItem {
  code: string
  name: string
  pct_change: number
  amount: number
  up_count: number
  down_count: number
  heat_score: number
  leader: ConceptLeader
}

export interface ConceptHeatListResponse {
  items: ConceptHeatItem[]
  updated_at: string
}

// Concept constituents
export interface ConceptConstituentItem {
  symbol: string
  name: string
  price: number | null
  pct_change: number | null
  amount: number | null
  amplitude: number | null
}

// Concept history
export interface ConceptHistoryRecord {
  date: string
  open: number
  close: number
  high: number
  low: number
  volume: number
  amount: number
  pct_change: number
}

// Stock concepts (reverse lookup + resonance)
export interface StockConceptItem {
  code: string
  name: string
  pct_change: number
  amount: number
  up_count: number
  down_count: number
  stock_rank_pct: number | null
  zt_count: number // real limit-up count (cross-matched with limit pool)
  dt_count: number // real limit-down count (cross-matched with limit pool)
}

export interface ConceptResonance {
  level: string // "none" | "weak" | "moderate" | "strong"
  concepts: string[]
  top_driver: string | null
  rank_in_driver: string // "领涨" | "跟涨" | "滞涨" | ""
}

export interface StockConceptsResult {
  symbol: string
  industry: string
  concepts: StockConceptItem[]
  resonance: ConceptResonance
}
