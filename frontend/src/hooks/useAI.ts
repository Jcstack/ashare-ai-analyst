import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { getAIAnalysis, getQuickInsight, triggerAnalysis, getMarketAIOverview, postMoveAnalysis } from "@/api/agent"

export function useAIAnalysis(symbol: string) {
  return useQuery({
    queryKey: ["ai-analysis", symbol],
    queryFn: () => getAIAnalysis(symbol),
    enabled: !!symbol,
    staleTime: 30 * 60 * 1000, // 30 minutes
    retry: 1,
  })
}

export function useQuickInsight(symbol: string) {
  return useQuery({
    queryKey: ["quick-insight", symbol],
    queryFn: () => getQuickInsight(symbol),
    enabled: !!symbol,
    staleTime: 5 * 60 * 1000, // 5 minutes
    retry: 1,
  })
}

export function useTriggerAnalysis(symbol: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => triggerAnalysis(symbol),
    onSuccess: (data) => {
      queryClient.setQueryData(["ai-analysis", symbol], data)
    },
  })
}

export function useMarketAIOverview() {
  return useQuery({
    queryKey: ["market-ai-overview"],
    queryFn: getMarketAIOverview,
    staleTime: 15 * 60 * 1000, // 15 minutes
    retry: 1,
  })
}

export function useMoveAnalysis() {
  return useMutation({
    mutationFn: ({
      symbol,
      position,
    }: {
      symbol: string
      position?: { cost_price: number; shares: number; holding_days: number }
    }) => postMoveAnalysis(symbol, position),
  })
}
