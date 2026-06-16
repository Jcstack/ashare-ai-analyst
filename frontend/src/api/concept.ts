import client from "./client"
import type {
  ConceptHeatListResponse,
  ConceptConstituentItem,
  ConceptHistoryRecord,
  StockConceptsResult,
} from "@/types/concept"

export async function fetchConceptHot(topN = 20): Promise<ConceptHeatListResponse> {
  const { data } = await client.get<ConceptHeatListResponse>("/concept/hot", {
    params: { top_n: topN },
  })
  return data
}

export async function fetchConceptConstituents(
  boardCode: string,
  sortBy: "pct_change" | "amount" = "pct_change",
): Promise<ConceptConstituentItem[]> {
  const { data } = await client.get<ConceptConstituentItem[]>(
    `/concept/${boardCode}/constituents`,
    { params: { sort_by: sortBy } },
  )
  return data
}

export async function fetchConceptHistory(
  boardCode: string,
  period = "daily",
  days = 60,
): Promise<ConceptHistoryRecord[]> {
  const { data } = await client.get<ConceptHistoryRecord[]>(
    `/concept/${boardCode}/history`,
    { params: { period, days } },
  )
  return data
}

export async function fetchStockConcepts(symbol: string): Promise<StockConceptsResult> {
  const { data } = await client.get<StockConceptsResult>(`/stock/${symbol}/concepts`)
  return data
}
