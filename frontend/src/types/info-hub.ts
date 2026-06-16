/** v21.0 Intelligence Hub types — mirrors backend schemas. */

// ─── Categories & Priorities ──────────────────────────────────────────────────

export type InfoCategory =
  | "policy"
  | "macro"
  | "industry"
  | "company"
  | "market"
  | "global"
  | "social"
  | "community"

export type InfoPriority = "breaking" | "high" | "normal" | "low"

export const CATEGORY_LABELS: Record<InfoCategory, string> = {
  policy: "政策法规",
  macro: "宏观经济",
  industry: "行业动态",
  company: "公司公告",
  market: "市场行情",
  global: "全球市场",
  social: "社会舆情",
  community: "社区讨论",
}

export const PRIORITY_LABELS: Record<InfoPriority, string> = {
  breaking: "突发",
  high: "重要",
  normal: "一般",
  low: "低",
}

export const PRIORITY_COLORS: Record<InfoPriority, string> = {
  breaking: "text-red-500",
  high: "text-orange-500",
  normal: "text-muted-foreground",
  low: "text-muted-foreground/60",
}

// ─── Data Models ──────────────────────────────────────────────────────────────

export interface InfoItem {
  item_id: string
  source_id: string
  source_name: string
  title: string
  summary: string
  url: string
  category: InfoCategory
  priority: InfoPriority
  tags: string[]
  related_symbols: string[]
  /** Stock code → name mapping for related_symbols (populated by backend SymbolExtractor). */
  related_symbol_names: Record<string, string>
  published_at: string
  fetched_at: string
  is_bookmarked: boolean
  is_read: boolean
  extra: Record<string, unknown>
  content_score: number | null
  score_explain: Record<string, unknown>
}

export interface FeedResponse {
  items: InfoItem[]
  total: number
}

export interface CategoryCount {
  category: InfoCategory
  total: number
  unread: number
}

export interface OverviewResponse {
  total_items: number
  sources_count: number
  categories: Record<string, { total: number; unread: number }>
}

export interface FeedParams {
  category?: string
  priority?: string
  search?: string
  bookmarked?: boolean
  symbol?: string
  limit?: number
  offset?: number
  days?: number
  sort_by?: "time" | "score"
}

export interface SourceHealth {
  source_id: string
  layer: string
  base_weight: number
  effective_weight: number
  compliance_level: string
  domain_tags: string[]
  status: "OK" | "WARN" | "DOWN"
  consecutive_failures: number
  avg_latency_ms: number
}

// ─── Event Clusters (v23.0 Event Explorer) ───────────────────────────────────

export interface EventCluster {
  cluster_id: string
  representative_title: string
  unique_sources: number
  cross_verification_score: number
  items: InfoItem[]
  earliest: string
  latest: string
}

export interface EventClustersResponse {
  clusters: EventCluster[]
}

// ─── Sub-page navigation items ────────────────────────────────────────────────

export interface SubPageItem {
  key: string
  label: string
  category?: InfoCategory
}

export const SUB_PAGES: SubPageItem[] = [
  { key: "all", label: "全部情报" },
  { key: "policy", label: "政策法规", category: "policy" },
  { key: "macro", label: "宏观经济", category: "macro" },
  { key: "industry", label: "行业动态", category: "industry" },
  { key: "company", label: "公司公告", category: "company" },
  { key: "market", label: "市场行情", category: "market" },
  { key: "global", label: "全球市场", category: "global" },
  { key: "events", label: "事件探索" },
  { key: "sources", label: "源管理" },
]
