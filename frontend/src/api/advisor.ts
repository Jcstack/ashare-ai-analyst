import client from "./client"
import type {
  StockAdvice,
  WatchlistStrategyResult,
  PortfolioAdviceResult,
  HolidayImpactResult,
  ReopenBriefingResult,
} from "@/types/advisor"

export async function fetchStockAdvice(symbol: string): Promise<StockAdvice> {
  const { data } = await client.get<StockAdvice>(`/advisor/stock/${symbol}`)
  return data
}

export async function fetchWatchlistStrategy(symbols: string[]): Promise<WatchlistStrategyResult> {
  const query = symbols.join(",")
  const { data } = await client.get<WatchlistStrategyResult>(`/advisor/watchlist?symbols=${query}`)
  return data
}

export async function fetchPortfolioAdvice(
  positions: Array<{ symbol: string; cost_price: number; shares: number }>,
): Promise<PortfolioAdviceResult> {
  const { data } = await client.post<PortfolioAdviceResult>("/advisor/portfolio", { positions })
  return data
}

export async function fetchHolidayImpact(symbol: string): Promise<HolidayImpactResult> {
  const { data } = await client.get<HolidayImpactResult>(`/advisor/holiday-impact/${symbol}`)
  return data
}

export async function fetchReopenBriefing(): Promise<ReopenBriefingResult> {
  const { data } = await client.get<ReopenBriefingResult>("/advisor/reopen-briefing")
  return data
}
