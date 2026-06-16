import { useQuery } from "@tanstack/react-query"
import { searchStocks } from "@/api/search"

export function useStockSearch(query: string) {
  return useQuery({
    queryKey: ["stock-search", query],
    queryFn: () => searchStocks(query),
    enabled: query.length >= 1,
    staleTime: 30_000,
  })
}
