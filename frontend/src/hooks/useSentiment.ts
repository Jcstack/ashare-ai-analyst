import { useQuery } from "@tanstack/react-query"
import {
  fetchResonanceEvents,
  fetchSentimentReport,
  fetchMarketPulse,
  fetchCrossMarket,
} from "@/api/sentiment"

/** Fetch resonance events, optionally filtered by watchlist symbols */
export function useResonanceEvents(symbols?: string[]) {
  return useQuery({
    queryKey: ["resonance-events", symbols?.join(",") ?? ""],
    queryFn: () => fetchResonanceEvents(symbols),
    staleTime: 5 * 60 * 1000, // 5min
    retry: 1,
  })
}

/** Fetch full AI structured sentiment report */
export function useSentimentReport(symbols?: string[], enabled = true) {
  return useQuery({
    queryKey: ["sentiment-report", symbols?.join(",") ?? ""],
    queryFn: () => fetchSentimentReport(symbols),
    staleTime: 30 * 60 * 1000, // 30min
    enabled,
    retry: 1,
  })
}

/** Fetch market pulse data for dashboard */
export function useMarketPulse(symbols?: string[]) {
  return useQuery({
    queryKey: ["market-pulse", symbols?.join(",") ?? ""],
    queryFn: () => fetchMarketPulse(symbols),
    staleTime: 5 * 60 * 1000, // 5min
    refetchInterval: 5 * 60 * 1000,
    retry: 1,
  })
}

/** Fetch cross-market correlation for a stock */
export function useCrossMarket(symbol: string, enabled = true) {
  return useQuery({
    queryKey: ["cross-market", symbol],
    queryFn: () => fetchCrossMarket(symbol),
    staleTime: 30 * 60 * 1000, // 30min
    enabled: !!symbol && enabled,
    retry: 1,
  })
}
