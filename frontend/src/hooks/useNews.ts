import { useQuery } from "@tanstack/react-query"
import { getStockNews, getStockAnomalies, getStockSentiment, getHotRank } from "@/api/news"

export function useStockNews(symbol: string, limit = 20) {
  return useQuery({
    queryKey: ["stock-news", symbol, limit],
    queryFn: () => getStockNews(symbol, limit),
    enabled: !!symbol,
    staleTime: 5 * 60 * 1000,
  })
}

export function useStockAnomalies(symbol: string) {
  return useQuery({
    queryKey: ["stock-anomalies", symbol],
    queryFn: () => getStockAnomalies(symbol),
    enabled: !!symbol,
    staleTime: 2 * 60 * 1000,
  })
}

export function useStockSentiment(symbol: string) {
  return useQuery({
    queryKey: ["stock-sentiment", symbol],
    queryFn: () => getStockSentiment(symbol),
    enabled: !!symbol,
    staleTime: 5 * 60 * 1000,
  })
}

export function useHotRank() {
  return useQuery({
    queryKey: ["hot-rank"],
    queryFn: getHotRank,
    staleTime: 5 * 60 * 1000,
  })
}
