import { useQuery } from "@tanstack/react-query"
import {
  fetchBayesianIndicators,
  fetchDragonTigerSeats,
  fetchDragonTigerStats,
  fetchDragonTigerAI,
  fetchChartEvents,
} from "@/api/analysis"

export function useBayesianIndicators(symbol: string) {
  return useQuery({
    queryKey: ["bayesian-indicators", symbol],
    queryFn: () => fetchBayesianIndicators(symbol),
    enabled: !!symbol,
    staleTime: 60 * 60 * 1000, // 1 hour
  })
}

export function useDragonTigerSeats(symbol: string) {
  return useQuery({
    queryKey: ["dragon-tiger-seats", symbol],
    queryFn: () => fetchDragonTigerSeats(symbol),
    enabled: !!symbol,
    staleTime: 30 * 60 * 1000, // 30 min
  })
}

export function useDragonTigerStats(symbol: string) {
  return useQuery({
    queryKey: ["dragon-tiger-stats", symbol],
    queryFn: () => fetchDragonTigerStats(symbol),
    enabled: !!symbol,
    staleTime: 30 * 60 * 1000,
  })
}

export function useDragonTigerAI(symbol: string) {
  return useQuery({
    queryKey: ["dragon-tiger-ai", symbol],
    queryFn: () => fetchDragonTigerAI(symbol),
    enabled: !!symbol,
    staleTime: 30 * 60 * 1000,
  })
}

export function useChartEvents(symbol: string) {
  return useQuery({
    queryKey: ["chart-events", symbol],
    queryFn: () => fetchChartEvents(symbol),
    enabled: !!symbol,
    staleTime: 5 * 60 * 1000, // 5 min
    refetchInterval: 5 * 60 * 1000,
  })
}
