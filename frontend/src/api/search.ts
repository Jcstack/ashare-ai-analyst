import client from "./client"
import type { StockSearchItem } from "@/types/search"

export async function searchStocks(
  query: string,
  limit: number = 20
): Promise<StockSearchItem[]> {
  const { data } = await client.get<StockSearchItem[]>("/stocks/search", {
    params: { q: query, limit },
  })
  return data
}
