import { useQuery } from "@tanstack/react-query"
import {
  fetchMarketIndices,
  fetchRealtimeQuotes,
  fetchDragonTiger,
  fetchLimitUp,
  fetchStockDragonTiger,
  fetchGlobalSnapshot,
  fetchTradingCalendar,
} from "@/api/market"

export function useMarketIndices() {
  return useQuery({
    queryKey: ["market-indices"],
    queryFn: fetchMarketIndices,
    refetchInterval: 10_000,
    staleTime: 5_000,
    gcTime: Infinity,
    placeholderData: (prev) => prev,
    retry: 3,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 10_000),
  })
}

export function useRealtimeQuotes() {
  return useQuery({
    queryKey: ["realtime-quotes"],
    queryFn: ({ signal }) => fetchRealtimeQuotes(undefined, signal),
    refetchInterval: 30_000, // Safety-net polling (WS/SSE preferred)
    staleTime: 5_000,
  })
}

export function useDragonTiger(startDate?: string, endDate?: string) {
  return useQuery({
    queryKey: ["dragon-tiger", startDate, endDate],
    queryFn: () => fetchDragonTiger(startDate, endDate),
    staleTime: 5 * 60 * 1000, // 5 minutes
  })
}

export function useLimitUp(date?: string) {
  return useQuery({
    queryKey: ["limit-up", date],
    queryFn: () => fetchLimitUp(date),
    staleTime: 5 * 60 * 1000,
  })
}

export function useStockDragonTiger(symbol: string) {
  return useQuery({
    queryKey: ["stock-dragon-tiger", symbol],
    queryFn: () => fetchStockDragonTiger(symbol),
    enabled: !!symbol,
    staleTime: 5 * 60 * 1000,
  })
}

export function useGlobalMarketSnapshot() {
  return useQuery({
    queryKey: ["global-market-snapshot"],
    queryFn: fetchGlobalSnapshot,
    refetchInterval: 5 * 60 * 1000, // 5 min polling
    staleTime: 2 * 60 * 1000,
    retry: 2,
  })
}

export function useTradingCalendar() {
  return useQuery({
    queryKey: ["trading-calendar"],
    queryFn: fetchTradingCalendar,
    staleTime: 60 * 1000, // 1 min
    refetchInterval: 60 * 1000,
  })
}
