import { useQuery } from "@tanstack/react-query"
import {
  fetchMacroFlowOverview,
  fetchMacroFlowHistory,
  fetchSectorFlow,
  fetchSectorHeatmap,
} from "@/api/capital-flow"
import type {
  MacroFlowOverview,
  MacroFlowHistoryResponse,
  SectorFlowResponse,
  HeatmapResponse,
} from "@/types/capital-flow"

export function useMacroFlowOverview() {
  return useQuery<MacroFlowOverview>({
    queryKey: ["capital-flow", "macro"],
    queryFn: fetchMacroFlowOverview,
    staleTime: 120_000,
    refetchInterval: 120_000,
  })
}

export function useMacroFlowHistory(days = 30) {
  return useQuery<MacroFlowHistoryResponse>({
    queryKey: ["capital-flow", "macro-history", days],
    queryFn: () => fetchMacroFlowHistory(days),
    staleTime: 300_000,
  })
}

export function useSectorFlow(
  type: "industry" | "concept" = "industry",
  period = "today",
) {
  return useQuery<SectorFlowResponse>({
    queryKey: ["capital-flow", "sectors", type, period],
    queryFn: () => fetchSectorFlow(type, period),
    staleTime: 120_000,
    refetchInterval: 120_000,
  })
}

export function useSectorHeatmap() {
  return useQuery<HeatmapResponse>({
    queryKey: ["capital-flow", "heatmap"],
    queryFn: fetchSectorHeatmap,
    staleTime: 120_000,
    refetchInterval: 120_000,
  })
}
