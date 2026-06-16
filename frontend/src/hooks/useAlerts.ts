import { useQuery } from "@tanstack/react-query"
import { getStockAlerts } from "@/api/agent"

export function useStockAlerts(symbol: string) {
  return useQuery({
    queryKey: ["stock-alerts", symbol],
    queryFn: () => getStockAlerts(symbol),
    enabled: !!symbol,
    staleTime: 2 * 60 * 1000,
    refetchInterval: 60 * 1000, // Auto-refresh alerts every minute
  })
}
