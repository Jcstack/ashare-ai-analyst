import { useQuery } from "@tanstack/react-query"
import { getRealtimeSnapshot } from "@/api/stocks"
import type { RealtimeSnapshot, IntradayTradesStats, TickRecord, FundFlowSnapshot, FundFlowDetailSnapshot } from "@/types/stock"

export function useRealtimeSnapshot(symbol: string) {
  return useQuery({
    queryKey: ["realtime-snapshot", symbol],
    queryFn: ({ signal }) => getRealtimeSnapshot(symbol, signal),
    enabled: !!symbol,
    staleTime: 30_000,
    refetchInterval: 30_000,
    placeholderData: (prev) => prev,
  })
}

export function selectTradesStats(snapshot: RealtimeSnapshot | undefined): IntradayTradesStats | null {
  return snapshot?.trades?.stats ?? null
}

export function selectRecentTicks(snapshot: RealtimeSnapshot | undefined): TickRecord[] {
  return snapshot?.trades?.recent_ticks ?? []
}

export function selectFundFlowIntraday(snapshot: RealtimeSnapshot | undefined): FundFlowSnapshot | null {
  return snapshot?.fund_flow ?? null
}

export function selectFundFlowDetail(snapshot: RealtimeSnapshot | undefined): FundFlowDetailSnapshot | null {
  return snapshot?.fund_flow_detail ?? null
}
