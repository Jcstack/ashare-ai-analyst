import client from "./client"
import type { ActionItem, BootstrapData, ReviewData, Thesis } from "@/types/action"

// ---------------------------------------------------------------------------
// Bootstrap — single call to hydrate Control Tower
// ---------------------------------------------------------------------------

export async function fetchBootstrap(): Promise<BootstrapData> {
  const { data } = await client.get<BootstrapData>("/bootstrap")
  return data
}

// ---------------------------------------------------------------------------
// Action Queue
// ---------------------------------------------------------------------------

export async function fetchActionQueue(): Promise<ActionItem[]> {
  const { data } = await client.get<{ actions: ActionItem[] }>("/actions/")
  return data.actions
}

export async function confirmAction(actionId: string): Promise<ActionItem> {
  const { data } = await client.post<ActionItem>(`/actions/${actionId}/confirm`)
  return data
}

export async function rejectAction(actionId: string): Promise<ActionItem> {
  const { data } = await client.post<ActionItem>(`/actions/${actionId}/reject`)
  return data
}

export async function recordFill(
  actionId: string,
  fill: { price: number; shares: number },
): Promise<ActionItem> {
  const { data } = await client.post<ActionItem>(`/actions/${actionId}/fill`, fill)
  return data
}

// ---------------------------------------------------------------------------
// Theses
// ---------------------------------------------------------------------------

export async function fetchTheses(): Promise<Thesis[]> {
  const { data } = await client.get<{ theses: Thesis[]; count: number }>("/theses")
  return data.theses
}

// ---------------------------------------------------------------------------
// Review
// ---------------------------------------------------------------------------

export async function fetchReview(date?: string): Promise<ReviewData> {
  const params = date ? { date } : {}
  // Backend nests pnl and signal_accuracy; flatten for frontend
  const { data } = await client.get<{
    date: string
    pnl: { daily: number; daily_pct: number; weekly: number; monthly: number }
    decisions: ReviewData["decisions"]
    signal_accuracy: { "30d": number; "7d": number }
    brier_score: number
    missed_opportunities: ReviewData["missed_opportunities"]
    ai_summary?: string
  }>("/review/daily", { params })
  return {
    date: data.date,
    daily_pnl: data.pnl?.daily ?? 0,
    daily_pnl_pct: data.pnl?.daily_pct ?? 0,
    decisions: data.decisions ?? [],
    signal_accuracy_30d: data.signal_accuracy?.["30d"] ?? 0,
    brier_score: data.brier_score ?? 0,
    missed_opportunities: data.missed_opportunities ?? [],
    ai_summary: data.ai_summary ?? "",
  }
}
