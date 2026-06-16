import client from "./client"
import type { AIAnalysisResult, QuickInsight, Alert, MarketAIOverview, MoveAnalysis, UnifiedAnalysis, ConversationResponse, AgentStatus, InvestmentThesis, DecisionOutcome, AccuracyStats, CycleResult, CalibrationReport } from "@/types/agent"

export async function getAIAnalysis(symbol: string): Promise<AIAnalysisResult> {
  const { data } = await client.get<AIAnalysisResult>(`/stock/${symbol}/ai-analysis`)
  return data
}

export async function getQuickInsight(symbol: string): Promise<QuickInsight> {
  const { data } = await client.get<QuickInsight>(`/stock/${symbol}/quick-insight`)
  return data
}

export async function triggerAnalysis(symbol: string): Promise<AIAnalysisResult> {
  const { data } = await client.post<AIAnalysisResult>(`/stock/${symbol}/analyze`)
  return data
}

export async function getStockAlerts(symbol: string): Promise<Alert[]> {
  const { data } = await client.get<Alert[]>(`/stock/${symbol}/alerts`)
  return data
}

export async function getMarketAIOverview(): Promise<MarketAIOverview> {
  const { data } = await client.get<MarketAIOverview>("/market/ai-overview")
  return data
}

export async function fetchUnifiedAnalysis(symbol: string): Promise<UnifiedAnalysis> {
  const { data } = await client.get<UnifiedAnalysis>(`/stock/${symbol}/unified-analysis`)
  return data
}

export async function postMoveAnalysis(
  symbol: string,
  position?: { cost_price: number; shares: number; holding_days: number },
): Promise<MoveAnalysis> {
  const { data } = await client.post<MoveAnalysis>(
    `/stock/${symbol}/move-analysis`,
    position ?? {},
  )
  return data
}

// ─── v11.0 Conversation API ────────────────────────────────────────────────

export interface IntelContext {
  item_ids: string[]
  analysis_angle?: string
  sector?: string
}

export async function startConversation(
  symbol: string,
  position?: { cost_price: number; shares: number; holding_days?: number },
  intelContext?: IntelContext,
): Promise<ConversationResponse> {
  const body: Record<string, unknown> = {}
  if (position) body.position = position
  if (intelContext) body.intel_context = intelContext
  const { data } = await client.post<ConversationResponse>(
    `/stock/${symbol}/conversation`,
    body,
  )
  return data
}

export async function sendFollowup(
  symbol: string,
  sessionId: string,
  message: string,
): Promise<ConversationResponse> {
  const { data } = await client.post<ConversationResponse>(
    `/stock/${symbol}/conversation`,
    { session_id: sessionId, message },
  )
  return data
}

export async function clearConversation(
  symbol: string,
  sessionId: string,
): Promise<void> {
  await client.delete(`/stock/${symbol}/conversation/${sessionId}`)
}

// ─── v34.0 Investment Agent (OODA) API ────────────────────────────────────────

export async function fetchAgentStatus(): Promise<AgentStatus> {
  const { data } = await client.get<AgentStatus>("/agent/status")
  return data
}

export async function fetchAgentTheses(includeInvalidated = false): Promise<InvestmentThesis[]> {
  const { data } = await client.get<InvestmentThesis[]>(
    `/agent/theses?include_invalidated=${includeInvalidated}`,
  )
  return data
}

export async function fetchAgentDecisions(limit = 20): Promise<DecisionOutcome[]> {
  const { data } = await client.get<DecisionOutcome[]>(`/agent/decisions?limit=${limit}`)
  return data
}

export async function fetchAgentAccuracy(lookbackDays = 30): Promise<AccuracyStats> {
  const { data } = await client.get<AccuracyStats>(
    `/agent/accuracy?lookback_days=${lookbackDays}`,
  )
  return data
}

export async function fetchCalibrationReport(): Promise<CalibrationReport> {
  const { data } = await client.get<CalibrationReport>("/agent/calibration")
  return data
}

export async function triggerAgentCycle(): Promise<CycleResult> {
  const { data } = await client.post<CycleResult>("/agent/cycle")
  return data
}
