/** Intelligence agent API client — v34.0 CIO dashboard & analysis endpoints. */

import client from "./client"
import type {
  DashboardData,
  DebateRecord,
  RotationPlan,
  ImpactChainResult,
  ChecklistResult,
  EquitySnapshot,
} from "@/types/cio-dashboard"

export async function getIntelligenceDashboard(): Promise<DashboardData> {
  const { data } = await client.get<DashboardData>("/intelligence/dashboard")
  return data
}

export async function runDebate(params: {
  symbol: string
  name?: string
  trigger?: string
  market_data?: Record<string, unknown>
}): Promise<DebateRecord> {
  const { data } = await client.post<DebateRecord>("/intelligence/debate", params)
  return data
}

export async function scanRotation(params?: {
  positions?: { symbol: string; name: string }[]
  macro?: Record<string, number>
}): Promise<{ position_count: number; rotation_plans: RotationPlan[]; plans_count: number }> {
  const { data } = await client.post("/intelligence/rotation-scan", params ?? {})
  return data
}

export async function analyzeImpactChain(eventText: string): Promise<ImpactChainResult> {
  const { data } = await client.post<ImpactChainResult>("/intelligence/impact-chain", {
    event_text: eventText,
  })
  return data
}

export async function runMungerChecklist(params: {
  symbol: string
  name?: string
  current_price?: number
  fair_value?: number
  recent_gain_pct?: number
  news_count_24h?: number
}): Promise<ChecklistResult> {
  const { data } = await client.post<ChecklistResult>("/intelligence/munger-checklist", params)
  return data
}

export async function checkConstraints(
  symbol: string,
  name?: string,
): Promise<{
  symbol: string
  name: string
  board: string
  passed: boolean
  blocked: boolean
  violations: { rule: string; severity: string; message: string }[]
}> {
  const { data } = await client.post("/intelligence/constraint-check", { symbol, name })
  return data
}

export interface MacroCalendarData {
  china: MacroReleaseItem[]
  us: MacroReleaseItem[]
  surprises: MacroReleaseItem[]
  total_releases: number
}

export interface MacroReleaseItem {
  indicator: string
  country: string
  date: string
  actual: number | null
  forecast: number | null
  previous: number | null
  surprise: number | null
  importance: string
}

export async function getMacroCalendar(nLatest = 3): Promise<MacroCalendarData> {
  const { data } = await client.get<MacroCalendarData>("/intelligence/macro-calendar", {
    params: { n_latest: nLatest },
  })
  return data
}

export async function getEquityCurve(
  days = 90,
): Promise<{ snapshots: EquitySnapshot[]; count: number }> {
  const { data } = await client.get("/intelligence/equity-curve", {
    params: { days },
  })
  return data
}

export interface FactorRadarItem {
  label: string
  value: number
  benchmark?: number
}

export async function getFactorExposure(): Promise<{
  factors: FactorRadarItem[]
  position_count: number
  available_count: number
}> {
  const { data } = await client.post("/intelligence/factor-exposure", {})
  return data
}

export async function getPortfolioOptimize(): Promise<{
  targets: {
    symbol: string
    name: string
    current_weight: number
    target_weight: number
    weight_delta: number
    alpha_score: number
    action: string
    reason: string
  }[]
  total_positions: number
  rebalance_needed: boolean
  risk_metrics: Record<string, number>
}> {
  const { data } = await client.post("/intelligence/portfolio-optimize", {})
  return data
}

export async function scanBlackSwan(
  indicators: Record<string, unknown>,
): Promise<{ alert_level: string; indicators: unknown[]; message?: string }> {
  const { data } = await client.post("/intelligence/black-swan-scan", indicators)
  return data
}
