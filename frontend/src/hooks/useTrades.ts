import { useQuery, keepPreviousData } from "@tanstack/react-query"
import { getTradeHistory, getTradingProfile } from "@/api/trade"

export function useTradeHistory(symbol?: string, limit = 20) {
  return useQuery({
    queryKey: ["trades", symbol ?? "", limit],
    queryFn: () => getTradeHistory({ symbol: symbol || undefined, limit }),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  })
}

export function useTradingProfile() {
  return useQuery({
    queryKey: ["trading-profile"],
    queryFn: getTradingProfile,
    staleTime: 60_000,
  })
}
