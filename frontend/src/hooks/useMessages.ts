/** React Query hooks for message feed. */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import {
  fetchMessages,
  fetchMessage,
  markMessageRead,
  fetchUnreadCount,
  fetchPerformanceSummary,
  fetchWatchlistWithAI,
} from "@/api/messages"

export function useMessages(params?: {
  type?: string
  filter?: string
  symbol?: string
  limit?: number
  offset?: number
}) {
  return useQuery({
    queryKey: ["messages", params],
    queryFn: () => fetchMessages(params),
    staleTime: 15_000,
    refetchInterval: 30_000,
  })
}

/** Get the latest agent signal (buy/sell) for a stock symbol. */
export function useLatestAgentSignal(symbol: string) {
  return useQuery({
    queryKey: ["agent-signal", symbol],
    queryFn: async () => {
      const res = await fetchMessages({
        symbol,
        type: "buy_signal,sell_signal,hold_update",
      })
      return res.items?.[0] ?? null
    },
    enabled: !!symbol,
    staleTime: 60_000,
  })
}

export function useMessageDetail(messageId: string | null) {
  return useQuery({
    queryKey: ["message-detail", messageId],
    queryFn: () => fetchMessage(messageId!),
    enabled: !!messageId,
    staleTime: 15_000,
  })
}

export function useMarkMessageRead() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: markMessageRead,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["messages"] })
      queryClient.invalidateQueries({ queryKey: ["message-unread-count"] })
    },
  })
}

export function useMessageUnreadCount() {
  return useQuery({
    queryKey: ["message-unread-count"],
    queryFn: fetchUnreadCount,
    staleTime: 60_000,
    refetchInterval: 120_000,
  })
}

// v36.0 hooks
export function usePerformanceSummary() {
  return useQuery({
    queryKey: ["performance-summary"],
    queryFn: fetchPerformanceSummary,
    staleTime: 120_000,
  })
}

export function useWatchlistWithAI() {
  return useQuery({
    queryKey: ["watchlist-ai"],
    queryFn: fetchWatchlistWithAI,
    staleTime: 30_000,
    refetchInterval: 60_000,
  })
}
