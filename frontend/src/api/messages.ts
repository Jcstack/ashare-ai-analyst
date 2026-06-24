/** API client for message feed endpoints. */

import client from "./client"
import type {
  MessageListResponse,
  Message,
  WatchlistStock,
  PerformanceSummary,
} from "@/types/message"

export async function fetchMessages(params?: {
  type?: string
  filter?: string
  symbol?: string
  limit?: number
  offset?: number
}): Promise<MessageListResponse> {
  const { data } = await client.get<MessageListResponse>("/messages", {
    params,
  })
  return data
}

export async function fetchMessage(messageId: string): Promise<Message> {
  const { data } = await client.get<Message>(`/messages/${messageId}`)
  return data
}

export async function markMessageRead(
  messageId: string
): Promise<{ success: boolean }> {
  const { data } = await client.post<{ success: boolean }>(
    `/messages/${messageId}/read`
  )
  return data
}

export async function fetchUnreadCount(): Promise<{ count: number }> {
  const { data } = await client.get<{ count: number }>("/messages/unread-count")
  return data
}

// v36.0 Performance API
export async function fetchPerformanceSummary(): Promise<PerformanceSummary> {
  const { data } = await client.get<PerformanceSummary>("/performance/summary")
  return data
}

// v36.0 Enhanced Watchlist API
export async function fetchWatchlistWithAI(): Promise<WatchlistStock[]> {
  const { data } = await client.get<WatchlistStock[]>("/watchlist")
  return data
}
