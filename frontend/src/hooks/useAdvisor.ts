import { useQuery } from "@tanstack/react-query"
import { fetchStockAdvice, fetchHolidayImpact, fetchReopenBriefing } from "@/api/advisor"

export function useStockAdvice(symbol: string, enabled = false) {
  return useQuery({
    queryKey: ["stock-advice", symbol],
    queryFn: () => fetchStockAdvice(symbol),
    enabled: !!symbol && enabled,
    staleTime: 30 * 60 * 1000, // 30 min
    gcTime: 60 * 60 * 1000,
    retry: 1,
  })
}

export function useHolidayImpact(symbol: string, enabled = false) {
  return useQuery({
    queryKey: ["holiday-impact", symbol],
    queryFn: () => fetchHolidayImpact(symbol),
    enabled: !!symbol && enabled,
    staleTime: 2 * 60 * 60 * 1000, // 2 hours
    gcTime: 4 * 60 * 60 * 1000,
    retry: 1,
  })
}

export function useReopenBriefing(enabled = false) {
  return useQuery({
    queryKey: ["reopen-briefing"],
    queryFn: fetchReopenBriefing,
    enabled,
    staleTime: 60 * 60 * 1000, // 1 hour
    retry: 1,
  })
}
