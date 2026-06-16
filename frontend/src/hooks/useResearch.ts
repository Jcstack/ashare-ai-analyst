import { useQuery } from "@tanstack/react-query"
import client from "@/api/client"

export interface ResearchData {
  symbol: string
  news: { title: string; datetime: string; source: string; url?: string }[]
  sentiment: {
    symbol: string
    overall: string
    positive_count: number
    negative_count: number
    neutral_count: number
    total_count: number
    score: number
    summary: string | null
  } | null
  fund_holdings: Record<string, unknown>[]
  analyst_ratings: Record<string, unknown>[]
}

async function fetchResearch(symbol: string): Promise<ResearchData> {
  const { data } = await client.get<ResearchData>(`/stock/${symbol}/research`)
  return data
}

export function useResearch(symbol: string) {
  return useQuery({
    queryKey: ["research", symbol],
    queryFn: () => fetchResearch(symbol),
    enabled: !!symbol,
    staleTime: 15 * 60_000, // 15 minutes
    retry: 1,
  })
}
