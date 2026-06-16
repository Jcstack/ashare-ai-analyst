/** Capital flow types — Per PRD v26.0 */

export interface MacroChannelItem {
  channel: "northbound" | "southbound" | "margin" | "etf"
  value: number
  direction: "up" | "down" | "flat"
}

export interface MacroFlowOverview {
  date: string
  environment_score: number
  signal: "bullish" | "bearish" | "neutral"
  northbound_net: number
  southbound_net: number
  margin_balance: number
  margin_balance_change: number
  etf_net_flow: number
  channels: MacroChannelItem[]
  interpretation: string
  updated_at: string
}

export interface MacroFlowHistoryItem {
  date: string
  environment_score: number
  signal: "bullish" | "bearish" | "neutral"
  northbound_net: number
  southbound_net: number
  margin_balance_change: number
  etf_net_flow: number
}

export interface MacroFlowHistoryResponse {
  days: number
  items: MacroFlowHistoryItem[]
}

/** Sector-level capital flow */

export interface SectorFlowItem {
  sector_name: string
  sector_type: "industry" | "concept"
  change_pct: number | null
  net_inflow: number
  main_net_inflow: number
  turnover: number
}

export interface SectorFlowResponse {
  type: string
  period: string
  items: SectorFlowItem[]
  interpretation: string
}

export interface HeatmapItem {
  name: string
  net_inflow: number
  change_pct: number
  turnover: number
  color_value: number // normalised [-1, 1]
}

export interface HeatmapResponse {
  items: HeatmapItem[]
  updated_at: string
}
