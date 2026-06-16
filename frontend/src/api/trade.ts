/** Trade API client — execute trades and manage recommendations. */

import client from "./client"

// ---------------------------------------------------------------------------
// Read-only types (match backend Trade / TradingProfile schemas)
// ---------------------------------------------------------------------------

export interface Trade {
  id: string
  symbol: string
  stock_name: string
  action: "buy" | "sell" | "add" | "reduce"
  shares: number
  price: number
  amount: number
  source: "agent" | "manual"
  reasoning: string
  status: string
  executed_at: string | null
  created_at: string
}

export interface TradeListResponse {
  trades: Trade[]
  total: number
}

export interface TradingProfile {
  total_trades: number
  win_rate: number
  avg_holding_days: number
  risk_tolerance: string
  common_biases: string[]
  preferred_sectors: string[]
  agent_adoption_rate: number
  last_updated: string
}

// ---------------------------------------------------------------------------
// Query functions
// ---------------------------------------------------------------------------

/** Fetch paginated trade history, optionally filtered by symbol. */
export async function getTradeHistory(
  params: { symbol?: string; limit?: number; offset?: number } = {},
): Promise<TradeListResponse> {
  const { data } = await client.get<TradeListResponse>("/trades", { params })
  return data
}

/** Fetch the user's trading behavior profile. */
export async function getTradingProfile(): Promise<TradingProfile> {
  const { data } = await client.get<TradingProfile>("/trades/profile")
  return data
}

export interface ExecuteTradeParams {
  symbol: string
  stock_name: string
  action: "buy" | "sell" | "add" | "reduce"
  shares: number
  price: number
  reasoning?: string
  thread_id?: string
  recommendation_id?: string
}

export interface ExecuteTradeResult {
  id: string
  symbol: string
  stock_name: string
  action: string
  shares: number
  price: number
  amount: number
  source: string
  status: string
}

// ---------------------------------------------------------------------------
// Manual trade
// ---------------------------------------------------------------------------

export interface ManualTradeParams {
  symbol: string
  stock_name: string
  action: "buy" | "sell" | "add" | "reduce"
  shares: number
  price: number
  reasoning?: string
  recommendation_id?: string
}

/** Record a manual trade via POST /trades/manual. */
export async function recordManualTrade(
  params: ManualTradeParams,
): Promise<Trade> {
  const { data } = await client.post<Trade>("/trades/manual", params)
  return data
}

/** Execute a simulated trade. */
export async function executeTrade(
  params: ExecuteTradeParams,
): Promise<ExecuteTradeResult> {
  const { data } = await client.post<ExecuteTradeResult>("/trades/execute", params)
  return data
}

/** Accept a recommendation (mark decision as "accepted"). */
export async function acceptRecommendation(
  recommendationId: string,
  feedback?: string,
): Promise<void> {
  await client.post(`/trades/recommendations/${recommendationId}/decision`, {
    decision: "accepted",
    feedback,
  })
}

/** Reject a recommendation (mark decision as "rejected"). */
export async function rejectRecommendation(
  recommendationId: string,
  feedback?: string,
): Promise<void> {
  await client.post(`/trades/recommendations/${recommendationId}/decision`, {
    decision: "rejected",
    feedback,
  })
}

// ---- Gate API (Simulation-First Execution Flow) ----

export interface CreateGateParams {
  trade_type: "buy" | "sell" | "add" | "reduce"
  symbol: string
  quantity: number
  price?: number
  thread_id?: string
  auto_risk_check?: boolean
}

export interface GateResponse {
  request_id: string
  symbol: string
  trade_type: string
  quantity: number
  price: number | null
  current_stage: string
  created_at: string
  updated_at: string
}

/** Create a confirmation gate for a trade. */
export async function createGate(
  params: CreateGateParams,
): Promise<GateResponse> {
  const { data } = await client.post<GateResponse>("/trades/gate", params)
  return data
}

/** Confirm a gate request (user approval step). */
export async function confirmGate(
  requestId: string,
  feedback?: string,
): Promise<GateResponse> {
  const { data } = await client.post<GateResponse>(
    `/trades/gate/${requestId}/confirm`,
    { feedback: feedback ?? "" },
  )
  return data
}

/** Get the current state of a gate request. */
export async function getGate(requestId: string): Promise<GateResponse> {
  const { data } = await client.get<GateResponse>(`/trades/gate/${requestId}`)
  return data
}
