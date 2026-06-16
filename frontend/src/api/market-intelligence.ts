/** Market Intelligence API client — 9 endpoints under /market-intelligence. */

import client from "./client"
import type {
  MarketSignal,
  TrendRadarResponse,
  AnomalyRadarResponse,
  SectorRotationResponse,
  CorrelationResponse,
  MacroRegimeResponse,
  TimelineEntry,
  SignalAccuracyResponse,
  AccuracyHistoryResponse,
} from "@/types/intelligence"

export async function getSignals(params?: {
  signal_type?: string
  asset?: string
  phase?: string
  limit?: number
  days?: number
}): Promise<MarketSignal[]> {
  const { data } = await client.get<MarketSignal[]>("/market-intelligence/signals", { params })
  return data
}

export async function getTrendRadar(): Promise<TrendRadarResponse> {
  const { data } = await client.get<TrendRadarResponse>("/market-intelligence/trend-radar")
  return data
}

export async function getAnomalyRadar(): Promise<AnomalyRadarResponse> {
  const { data } = await client.get<AnomalyRadarResponse>("/market-intelligence/anomaly-radar")
  return data
}

export async function getSectorRotation(): Promise<SectorRotationResponse> {
  const { data } = await client.get<SectorRotationResponse>("/market-intelligence/sector-rotation")
  return data
}

export async function getCorrelation(
  symbols: string[],
  lookbackDays?: number,
): Promise<CorrelationResponse> {
  const { data } = await client.get<CorrelationResponse>("/market-intelligence/correlation", {
    params: { symbols: symbols.join(","), lookback_days: lookbackDays },
  })
  return data
}

export async function getMacroRegime(): Promise<MacroRegimeResponse> {
  const { data } = await client.get<MacroRegimeResponse>("/market-intelligence/macro-regime")
  return data
}

export async function getTimeline(params?: {
  limit?: number
  days?: number
}): Promise<TimelineEntry[]> {
  const { data } = await client.get<TimelineEntry[]>("/market-intelligence/timeline", { params })
  return data
}

export async function getSignalAccuracy(params?: {
  signal_type?: string
  window_days?: number
}): Promise<SignalAccuracyResponse> {
  const { data } = await client.get<SignalAccuracyResponse>("/market-intelligence/signal-accuracy", {
    params,
  })
  return data
}

export async function getAccuracyHistory(params?: {
  signal_type?: string
  granularity?: "daily" | "weekly"
  window_days?: number
}): Promise<AccuracyHistoryResponse> {
  const { data } = await client.get<AccuracyHistoryResponse>(
    "/market-intelligence/signal-accuracy/history",
    { params },
  )
  return data
}
