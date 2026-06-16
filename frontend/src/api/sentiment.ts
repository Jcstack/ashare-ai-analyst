import client from "./client"
import type {
  ResonanceResult,
  SentimentReport,
  MarketPulseResult,
  CrossMarketResult,
} from "@/types/sentiment"

export async function fetchResonanceEvents(symbols?: string[]): Promise<ResonanceResult> {
  const params = symbols?.length ? `?symbols=${symbols.join(",")}` : ""
  const { data } = await client.get<ResonanceResult>(`/sentiment/resonance${params}`)
  return data
}

export async function fetchSentimentReport(symbols?: string[]): Promise<SentimentReport> {
  const params = symbols?.length ? `?symbols=${symbols.join(",")}` : ""
  const { data } = await client.get<SentimentReport>(`/sentiment/report${params}`)
  return data
}

export async function fetchMarketPulse(symbols?: string[]): Promise<MarketPulseResult> {
  const params = symbols?.length ? `?symbols=${symbols.join(",")}` : ""
  const { data } = await client.get<MarketPulseResult>(`/sentiment/market-pulse${params}`)
  return data
}

export async function fetchCrossMarket(symbol: string): Promise<CrossMarketResult> {
  const { data } = await client.get<CrossMarketResult>(`/sentiment/cross-market/${symbol}`)
  return data
}
