import client from "./client"
import type {
  RealtimeQuote,
  DragonTigerItem,
  LimitUpItem,
  MarketIndex,
  MarketStatus,
  GlobalMarketSnapshot,
  TradingCalendarInfo,
} from "@/types/market"

let _lastGoodCount = 0

export async function fetchMarketIndices(): Promise<MarketIndex[]> {
  const { data } = await client.get<MarketIndex[]>("/market/indices")
  if (data.length === 0 && _lastGoodCount > 0) {
    throw new Error("Empty indices response — retaining cached data")
  }
  if (data.length > 0 && data.length < _lastGoodCount) {
    throw new Error("Partial indices response — retaining cached data")
  }
  if (data.length > 0) {
    _lastGoodCount = data.length
  }
  return data
}

export async function fetchRealtimeQuotes(
  symbols?: string[],
  signal?: AbortSignal,
): Promise<RealtimeQuote[]> {
  const params = symbols?.length ? `?symbols=${symbols.join(",")}` : ""
  const { data } = await client.get<RealtimeQuote[]>(`/market/realtime${params}`, { signal })
  return data
}

export async function fetchDragonTiger(startDate?: string, endDate?: string): Promise<DragonTigerItem[]> {
  const params = new URLSearchParams()
  if (startDate) params.set("start_date", startDate)
  if (endDate) params.set("end_date", endDate)
  const query = params.toString() ? `?${params.toString()}` : ""
  const { data } = await client.get<DragonTigerItem[]>(`/market/dragon-tiger${query}`)
  return data
}

export async function fetchLimitUp(date?: string): Promise<LimitUpItem[]> {
  const params = date ? `?date=${date}` : ""
  const { data } = await client.get<LimitUpItem[]>(`/market/limit-up${params}`)
  return data
}

export async function fetchStockDragonTiger(symbol: string, days = 30): Promise<DragonTigerItem[]> {
  const { data } = await client.get<DragonTigerItem[]>(`/market/dragon-tiger/${symbol}?days=${days}`)
  return data
}

export async function fetchGlobalSnapshot(): Promise<GlobalMarketSnapshot> {
  const { data } = await client.get<GlobalMarketSnapshot>("/global-market/snapshot")
  return data
}

export async function fetchTradingCalendar(): Promise<TradingCalendarInfo> {
  const { data } = await client.get<TradingCalendarInfo>("/market/calendar")
  return data
}

export async function fetchMarketStatus(): Promise<MarketStatus> {
  const { data } = await client.get<MarketStatus>("/market/status")
  return data
}
