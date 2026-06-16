import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { getWatchlist, getStockDetail, getOHLCV, getIndicators, getIndicatorsFull, getPatterns, getSupportResistance, getIndicatorExplanations, getIntradayTrades } from "@/api/stocks"
import { addToWatchlist, removeFromWatchlist } from "@/api/settings"
import type { WatchlistItem } from "@/types/stock"

export function useWatchlist() {
  return useQuery({
    queryKey: ["watchlist"],
    queryFn: getWatchlist,
    staleTime: 30_000, // 30s — config rarely changes
  })
}

export function useStockDetail(symbol: string) {
  return useQuery({
    queryKey: ["stock", symbol],
    queryFn: () => getStockDetail(symbol),
    enabled: !!symbol,
    staleTime: 60_000, // 60s — metadata is stable
  })
}

export function useOHLCV(symbol: string, period: string = "daily") {
  const isMinute = ["1", "5", "15", "30", "60", "timeline"].includes(period)
  return useQuery({
    queryKey: ["ohlcv", symbol, period],
    queryFn: () => getOHLCV(symbol, period),
    enabled: !!symbol,
    staleTime: isMinute ? 30_000 : 5 * 60_000,
    retry: isMinute ? 1 : 2, // fewer retries for intraday (fast fail on 404)
  })
}

export function useIntradayTrades(symbol: string) {
  return useQuery({
    queryKey: ["intraday-trades", symbol],
    queryFn: () => getIntradayTrades(symbol),
    enabled: !!symbol,
    staleTime: 60_000,
  })
}

export function useIndicators(symbol: string) {
  return useQuery({
    queryKey: ["indicators", symbol],
    queryFn: () => getIndicators(symbol),
    enabled: !!symbol,
    staleTime: 5 * 60_000,
  })
}

export function useIndicatorsFull(symbol: string) {
  return useQuery({
    queryKey: ["indicators-full", symbol],
    queryFn: () => getIndicatorsFull(symbol),
    enabled: !!symbol,
    staleTime: 5 * 60_000,
  })
}

export function usePatterns(symbol: string) {
  return useQuery({
    queryKey: ["patterns", symbol],
    queryFn: () => getPatterns(symbol),
    enabled: !!symbol,
    staleTime: 5 * 60_000,
  })
}

export function useSupportResistance(symbol: string) {
  return useQuery({
    queryKey: ["support-resistance", symbol],
    queryFn: () => getSupportResistance(symbol),
    enabled: !!symbol,
    staleTime: 5 * 60_000,
  })
}

export function useIndicatorExplanations() {
  return useQuery({
    queryKey: ["indicator-explanations"],
    queryFn: getIndicatorExplanations,
    staleTime: Infinity, // Static data, never refetch
  })
}

export function useAddToWatchlist() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: addToWatchlist,
    onMutate: async (newItem) => {
      await queryClient.cancelQueries({ queryKey: ["watchlist"] })
      const previous = queryClient.getQueryData<WatchlistItem[]>(["watchlist"])
      queryClient.setQueryData<WatchlistItem[]>(["watchlist"], (old = []) => [
        ...old,
        {
          symbol: newItem.symbol,
          name: newItem.name,
          board: newItem.board,
          close: null,
          change: null,
          pct_change: null,
          volume: null,
          open: null,
          high: null,
          low: null,
        } as WatchlistItem,
      ])
      return { previous }
    },
    onError: (_err, _newItem, context) => {
      if (context?.previous) {
        queryClient.setQueryData(["watchlist"], context.previous)
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["watchlist"] })
    },
  })
}

export function useRemoveFromWatchlist() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: removeFromWatchlist,
    onMutate: async (symbol) => {
      await queryClient.cancelQueries({ queryKey: ["watchlist"] })
      const previous = queryClient.getQueryData<WatchlistItem[]>(["watchlist"])
      queryClient.setQueryData<WatchlistItem[]>(["watchlist"], (old = []) =>
        old.filter((item) => item.symbol !== symbol),
      )
      return { previous }
    },
    onError: (_err, _symbol, context) => {
      if (context?.previous) {
        queryClient.setQueryData(["watchlist"], context.previous)
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["watchlist"] })
    },
  })
}
