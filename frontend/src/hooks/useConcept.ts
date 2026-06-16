import { useQuery } from "@tanstack/react-query"
import {
  fetchConceptHot,
  fetchConceptConstituents,
  fetchConceptHistory,
  fetchStockConcepts,
} from "@/api/concept"

/** Fetch concept heat ranking */
export function useConceptHot(topN = 20, enabled = true) {
  return useQuery({
    queryKey: ["concept-hot", topN],
    queryFn: () => fetchConceptHot(topN),
    staleTime: 5 * 60 * 1000, // 5min
    enabled,
    retry: 1,
  })
}

/** Fetch constituent stocks for a concept board */
export function useConceptConstituents(
  boardCode: string,
  sortBy: "pct_change" | "amount" = "pct_change",
  enabled = true,
) {
  return useQuery({
    queryKey: ["concept-constituents", boardCode, sortBy],
    queryFn: () => fetchConceptConstituents(boardCode, sortBy),
    staleTime: 5 * 60 * 1000,
    enabled: !!boardCode && enabled,
    retry: 1,
  })
}

/** Fetch historical OHLCV for a concept board */
export function useConceptHistory(
  boardCode: string,
  period = "daily",
  days = 60,
  enabled = true,
) {
  return useQuery({
    queryKey: ["concept-history", boardCode, period, days],
    queryFn: () => fetchConceptHistory(boardCode, period, days),
    staleTime: 30 * 60 * 1000, // 30min
    enabled: !!boardCode && enabled,
    retry: 1,
  })
}

/** Fetch stock's associated concepts with resonance analysis */
export function useStockConcepts(symbol: string) {
  return useQuery({
    queryKey: ["stock-concepts", symbol],
    queryFn: () => fetchStockConcepts(symbol),
    staleTime: 10 * 60 * 1000, // 10min
    enabled: !!symbol,
    retry: 1,
  })
}
