import client from "./client"
import type { StockNewsItem, AnomalyItem, SentimentSummary, HotRankItem } from "@/types/news"

export async function getStockNews(symbol: string, limit = 20): Promise<StockNewsItem[]> {
  const { data } = await client.get<StockNewsItem[]>(`/stock/${symbol}/news`, { params: { limit } })
  return data
}

export async function getStockAnomalies(symbol: string): Promise<AnomalyItem[]> {
  const { data } = await client.get<AnomalyItem[]>(`/stock/${symbol}/anomalies`)
  return data
}

export async function getStockSentiment(symbol: string): Promise<SentimentSummary> {
  const { data } = await client.get<SentimentSummary>(`/stock/${symbol}/sentiment`)
  return data
}

export async function getHotRank(): Promise<HotRankItem[]> {
  const { data } = await client.get<HotRankItem[]>("/market/hot-rank")
  return data
}
