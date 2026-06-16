/** React Query hooks for v20.0 Market Intelligence endpoints. */

import { useQuery } from "@tanstack/react-query"
import {
  getSignals,
  getTrendRadar,
  getAnomalyRadar,
  getSectorRotation,
  getCorrelation,
  getMacroRegime,
  getTimeline,
  getSignalAccuracy,
  getAccuracyHistory,
} from "@/api/market-intelligence"
import {
  getUserFollows,
  updateUserFollows,
  getNotificationPrefs,
  updateNotificationPrefs,
} from "@/api/user-config"

// ─── Signal hooks (staleTime: 30s) ──────────────────────────────────────────

const SIGNAL_STALE = 30 * 1000

export function useSignals(params?: {
  signal_type?: string
  asset?: string
  phase?: string
  limit?: number
  days?: number
}) {
  return useQuery({
    queryKey: ["market-intelligence", "signals", params],
    queryFn: () => getSignals(params),
    staleTime: SIGNAL_STALE,
  })
}

export function useTrendRadar() {
  return useQuery({
    queryKey: ["market-intelligence", "trend-radar"],
    queryFn: getTrendRadar,
    staleTime: SIGNAL_STALE,
  })
}

export function useAnomalyRadar() {
  return useQuery({
    queryKey: ["market-intelligence", "anomaly-radar"],
    queryFn: getAnomalyRadar,
    staleTime: SIGNAL_STALE,
  })
}

export function useTimeline(params?: { limit?: number; days?: number }) {
  return useQuery({
    queryKey: ["market-intelligence", "timeline", params],
    queryFn: () => getTimeline(params),
    staleTime: SIGNAL_STALE,
  })
}

// ─── Slower-moving data (staleTime: 5min) ────────────────────────────────────

const SLOW_STALE = 5 * 60 * 1000

export function useSectorRotation() {
  return useQuery({
    queryKey: ["market-intelligence", "sector-rotation"],
    queryFn: getSectorRotation,
    staleTime: SLOW_STALE,
  })
}

export function useCorrelation(symbols: string[], lookbackDays?: number) {
  return useQuery({
    queryKey: ["market-intelligence", "correlation", symbols, lookbackDays],
    queryFn: () => getCorrelation(symbols, lookbackDays),
    enabled: symbols.length >= 2,
    staleTime: SLOW_STALE,
  })
}

export function useMacroRegime() {
  return useQuery({
    queryKey: ["market-intelligence", "macro-regime"],
    queryFn: getMacroRegime,
    staleTime: SLOW_STALE,
  })
}

export function useSignalAccuracy(params?: {
  signal_type?: string
  window_days?: number
}) {
  return useQuery({
    queryKey: ["market-intelligence", "signal-accuracy", params],
    queryFn: () => getSignalAccuracy(params),
    staleTime: SLOW_STALE,
  })
}

export function useAccuracyHistory(params?: {
  signal_type?: string
  granularity?: "daily" | "weekly"
  window_days?: number
}) {
  return useQuery({
    queryKey: ["market-intelligence", "accuracy-history", params],
    queryFn: () => getAccuracyHistory(params),
    staleTime: SLOW_STALE,
  })
}

// ─── Phase info (derived from signals) ───────────────────────────────────────

export function usePhaseInfo() {
  return useQuery({
    queryKey: ["market-intelligence", "signals", { limit: 1 }],
    queryFn: () => getSignals({ limit: 1 }),
    staleTime: SIGNAL_STALE,
    select: (signals) => {
      if (signals.length === 0) return null
      return { phase: signals[0].phase, timestamp: signals[0].timestamp }
    },
  })
}

// ─── User follows & notification prefs ───────────────────────────────────────

export function useUserFollows() {
  return useQuery({
    queryKey: ["user", "follows"],
    queryFn: getUserFollows,
    staleTime: SLOW_STALE,
  })
}

export { updateUserFollows }

export function useNotificationPrefs() {
  return useQuery({
    queryKey: ["user", "notification-prefs"],
    queryFn: getNotificationPrefs,
    staleTime: SLOW_STALE,
  })
}

export { updateNotificationPrefs }
