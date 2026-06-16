import client from "./client"
import type {
  MacroFlowOverview,
  MacroFlowHistoryResponse,
  SectorFlowResponse,
  HeatmapResponse,
} from "@/types/capital-flow"

export async function fetchMacroFlowOverview(): Promise<MacroFlowOverview> {
  const { data } = await client.get<MacroFlowOverview>("/capital-flow/macro")
  return data
}

export async function fetchMacroFlowHistory(days = 30): Promise<MacroFlowHistoryResponse> {
  const { data } = await client.get<MacroFlowHistoryResponse>(`/capital-flow/macro/history?days=${days}`)
  return data
}

export async function fetchSectorFlow(
  type: "industry" | "concept" = "industry",
  period = "today",
): Promise<SectorFlowResponse> {
  const { data } = await client.get<SectorFlowResponse>(
    `/capital-flow/sectors?type=${type}&period=${period}`,
  )
  return data
}

export async function fetchSectorHeatmap(): Promise<HeatmapResponse> {
  const { data } = await client.get<HeatmapResponse>("/capital-flow/sectors/heatmap")
  return data
}
