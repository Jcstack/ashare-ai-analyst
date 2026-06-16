import { useQuery } from "@tanstack/react-query"
import { fetchMarketStatus } from "@/api/market"
import type { MarketStatus } from "@/types/market"

export function useMarketStatus() {
  return useQuery<MarketStatus>({
    queryKey: ["market-status"],
    queryFn: fetchMarketStatus,
    staleTime: 15_000,
    refetchInterval: 30_000,
  })
}
