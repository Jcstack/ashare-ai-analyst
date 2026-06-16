import client from "./client"
import type {
  BayesianAnalysisResult,
  DragonTigerSeatItem,
  DragonTigerStockStats,
  DragonTigerAIResult,
  ChartEventsResult,
} from "@/types/analysis"

export async function fetchBayesianIndicators(symbol: string): Promise<BayesianAnalysisResult> {
  const { data } = await client.get<BayesianAnalysisResult>(`/stock/${symbol}/indicators/bayesian`)
  return data
}

export async function fetchDragonTigerSeats(symbol: string): Promise<DragonTigerSeatItem[]> {
  const { data } = await client.get<DragonTigerSeatItem[]>(`/market/dragon-tiger/${symbol}/seats`)
  return data
}

export async function fetchDragonTigerStats(symbol: string): Promise<DragonTigerStockStats> {
  const { data } = await client.get<DragonTigerStockStats>(`/market/dragon-tiger/${symbol}/stats`)
  return data
}

export async function fetchDragonTigerAI(symbol: string): Promise<DragonTigerAIResult> {
  const { data } = await client.get<DragonTigerAIResult>(`/stock/${symbol}/dragon-tiger/ai-analysis`)
  return data
}

export async function fetchChartEvents(symbol: string, days = 120): Promise<ChartEventsResult> {
  const { data } = await client.get<ChartEventsResult>(`/stock/${symbol}/chart-events?days=${days}`)
  return data
}
