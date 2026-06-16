import client from "./client"
import type { WatchlistItem, StockDetail, OHLCVRecord, IndicatorsSummary, IndicatorsFullRecord, PatternDetection, SupportResistanceLevel, IntradayTradesStats, RealtimeSnapshot } from "@/types/stock"

export async function getWatchlist(): Promise<WatchlistItem[]> {
  const { data } = await client.get<WatchlistItem[]>("/watchlist")
  return data
}

export async function getStockDetail(symbol: string): Promise<StockDetail> {
  const { data } = await client.get<StockDetail>(`/stock/${symbol}`)
  return data
}

export async function getOHLCV(symbol: string, period: string = "daily"): Promise<OHLCVRecord[]> {
  const { data } = await client.get<OHLCVRecord[]>(`/stock/${symbol}/ohlcv`, { params: { period } })
  return data
}

export async function getIntradayTrades(symbol: string): Promise<IntradayTradesStats> {
  const { data } = await client.get<IntradayTradesStats>(`/stock/${symbol}/intraday-trades`)
  return data
}

export async function getIndicators(symbol: string): Promise<IndicatorsSummary> {
  const { data } = await client.get<IndicatorsSummary>(`/stock/${symbol}/indicators`)
  return data
}

export async function getIndicatorsFull(symbol: string): Promise<IndicatorsFullRecord[]> {
  const { data } = await client.get<IndicatorsFullRecord[]>(`/stock/${symbol}/indicators/full`)
  return data
}

export async function getPatterns(symbol: string): Promise<PatternDetection[]> {
  const { data } = await client.get<PatternDetection[]>(`/stock/${symbol}/patterns`)
  return data
}

export async function getSupportResistance(symbol: string): Promise<SupportResistanceLevel[]> {
  const { data } = await client.get<SupportResistanceLevel[]>(`/stock/${symbol}/support-resistance`)
  return data
}

export async function getRealtimeSnapshot(symbol: string, signal?: AbortSignal): Promise<RealtimeSnapshot> {
  const { data } = await client.get<RealtimeSnapshot>(`/stock/${symbol}/realtime-snapshot`, { signal })
  return data
}

export async function getIndicatorExplanations(): Promise<Record<string, IndicatorExplanation>> {
  const { data } = await client.get<Record<string, IndicatorExplanation>>("/indicators/explanations")
  return data
}

export interface IndicatorExplanation {
  name: string
  short_desc: string
  full_desc: string
  params?: Record<string, string>
  signals: Record<string, string>
  beginner_tip: string
}
