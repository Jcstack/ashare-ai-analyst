import client from "./client"
import type { ApiResponse } from "@/types/admin"

export async function getConfig(section: string): Promise<{ section: string; config: Record<string, unknown> }> {
  const { data } = await client.get<{ section: string; config: Record<string, unknown> }>(`/settings/config/${section}`)
  return data
}

export async function updateWatchlist(watchlist: Array<{ symbol: string; name: string; board: string }>): Promise<ApiResponse> {
  const { data } = await client.post<ApiResponse>("/settings/watchlist", { watchlist })
  return data
}

export async function addToWatchlist(item: { symbol: string; name: string; board: string }): Promise<ApiResponse> {
  const { data } = await client.post<ApiResponse>("/settings/watchlist/add", item)
  return data
}

export async function removeFromWatchlist(symbol: string): Promise<ApiResponse> {
  const { data } = await client.delete<ApiResponse>(`/settings/watchlist/${symbol}`)
  return data
}
