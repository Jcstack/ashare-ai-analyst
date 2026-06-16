/** Holiday Research Workbench types (v3.2 + v3.4 Deep Association) */

export interface UserNote {
  id: string
  content: string
  note_type: "observation" | "box_office" | "industry_report" | "policy" | "custom"
  created_at: string
}

// --- v3.4: Association Profile ---

export interface ConceptLink {
  code: string
  name: string
  pct_change: number
  rank_pct: number | null
}

export interface PeerLink {
  symbol: string
  market: "us" | "hk" | "commodity"
  tags: string[]
}

export interface IndustryProfile {
  tag: string
  display: string
  key_metrics: string[]
  seasonal_events: Record<string, { name: string; months: number[]; importance: string }>
  value_chain: string[]
  research_hints: Record<string, string>
  concept_keywords: string[]
}

export interface AssociationProfile {
  symbol: string
  industry: string
  concepts: ConceptLink[]
  resonance_level: "none" | "weak" | "moderate" | "strong"
  cross_market_peers: PeerLink[]
  cross_market_tags: string[]
  keyword_themes: string[]
  industry_profile: IndustryProfile | null
}

// --- v3.4: Research Questions ---

export interface ResearchQuestion {
  id: string
  category: "industry_event" | "competitor" | "policy" | "macro" | "cross_market" | "supply_chain"
  text: string
  priority: "high" | "medium" | "low"
  data_hint: string
  status: "pending" | "answered"
}

export interface ResearchChecklist {
  status: string
  symbol: string
  questions: ResearchQuestion[]
  generated_at: string
}

// --- v3.4: Structured Evidence ---

export interface EvidenceItem {
  id: string
  content: string
  evidence_type: "data_point" | "observation" | "source_link" | "analysis"
  linked_question_id: string
  impact: "bullish" | "bearish" | "neutral"
  confidence: "low" | "medium" | "high"
  source: string
  created_at: string
}

// --- v3.4: Scenario Analysis ---

export interface Scenario {
  name: string
  description: string
  key_assumptions: string[]
}

export interface ScenarioPriceImpact {
  direction: "up" | "down" | "flat"
  magnitude: "small" | "medium" | "large"
}

export interface ScenarioResult {
  name: string
  probability: "low" | "medium" | "high"
  price_impact: ScenarioPriceImpact
  key_drivers: string[]
  risks: string[]
  reasoning: string
}

export interface ScenarioAnalysisResult {
  status: string
  symbol: string
  scenarios: ScenarioResult[]
  generated_at: string
  disclaimer: string
}

// --- Context ---

export interface HolidayResearchContext {
  status: string
  symbol: string
  holiday_key: string
  news: Array<{
    title: string
    datetime: string
    source: string
    url: string
  }>
  concepts: Array<{
    name: string
    pct_change: number
    rank_in_concept: number
    concept_size: number
  }>
  global_market: {
    indices?: Array<{ name: string; pct_change: number }>
    commodities?: Array<{ name: string; pct_change: number }>
    currencies?: Array<{ name: string; pct_change: number }>
  }
  cross_market: {
    overall_score?: number
    overall_direction?: string
    us_peers?: Array<{ name: string; change_pct: number }>
    hk_peers?: Array<{ name: string; change_pct: number }>
    [key: string]: unknown
  }
  sentiment_matches: Array<{
    title: string
    platform: string
    heat_score: number
  }>
  user_notes: UserNote[]
  calendar_info: {
    is_holiday_period?: boolean
    next_trading_day?: string
    current_session?: string
  }
  association_profile: AssociationProfile | null
}

// --- Analysis ---

export interface BusinessFactor {
  name: string
  impact: "positive" | "negative" | "neutral"
  weight: number
  analysis: string
}

export interface SectorAnalysis {
  summary: string
  key_concepts: string[]
  sector_trend: "bullish" | "bearish" | "neutral"
}

export interface PeerComparison {
  summary: string
  us_peers: Array<{ name: string; change_pct: number }>
  hk_peers: Array<{ name: string; change_pct: number }>
}

export interface RiskItem {
  risk: string
  probability: "low" | "medium" | "high"
  impact: "low" | "medium" | "high"
  mitigation: string
}

export interface ReopeningStrategy {
  action: string
  confidence: number
  reasoning: string
  target_range: number[]
  stop_loss: number | null
}

export interface ComprehensiveAnalysisResult {
  status: string
  symbol: string
  business_factors: BusinessFactor[]
  sector_analysis: SectorAnalysis
  peer_comparison: PeerComparison
  risk_matrix: RiskItem[]
  reopening_strategy: ReopeningStrategy
  key_watch_items: string[]
  overall_assessment: string
  generated_at: string
  disclaimer: string
  evidence_completeness: number
  association_context: string
}

export interface ConversationMessage {
  role: "user" | "assistant"
  content: string
  timestamp: string
}

export interface FollowupResponse {
  status: string
  question: string
  answer: string
  generated_at: string
  disclaimer: string
  messages: ConversationMessage[]
}

// --- Profile Overrides ---

export interface ProfileOverride {
  symbol: string
  has_override: boolean
  added_concepts: Array<{ code: string; name: string }>
  removed_concept_codes: string[]
  added_peers: Array<{ symbol: string; market: string; tags: string[] }>
  removed_peer_symbols: string[]
  added_keywords: string[]
  removed_keywords: string[]
  industry_override: string | null
  updated_at: string
}

export interface ProfileOverrideRequest {
  added_concepts?: Array<{ code: string; name: string }>
  removed_concept_codes?: string[]
  added_peers?: Array<{ symbol: string; market: string; tags: string[] }>
  removed_peer_symbols?: string[]
  added_keywords?: string[]
  removed_keywords?: string[]
  industry_override?: string | null
}

export interface IndustryOption {
  tag: string
  display: string
}
