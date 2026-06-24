/** React Query hooks for AI news feed. */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import {
  fetchAiNews,
  fetchAiNewsSources,
  fetchAiNewsUnreadCount,
  markAiNewsRead,
  refreshAiNews,
} from "@/api/aiNews"

export function useAiNews(params?: {
  category?: string
  source?: string
  search?: string
  unread_only?: boolean
  limit?: number
  offset?: number
}) {
  return useQuery({
    queryKey: ["ai-news", params],
    queryFn: () => fetchAiNews(params),
    staleTime: 60_000,
    refetchInterval: 5 * 60_000, // 5min auto-refresh
  })
}

export function useAiNewsSources() {
  return useQuery({
    queryKey: ["ai-news-sources"],
    queryFn: fetchAiNewsSources,
    staleTime: 120_000,
  })
}

export function useAiNewsUnreadCount() {
  return useQuery({
    queryKey: ["ai-news-unread"],
    queryFn: fetchAiNewsUnreadCount,
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  })
}

export function useMarkAiNewsRead() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: markAiNewsRead,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ai-news"] })
      queryClient.invalidateQueries({ queryKey: ["ai-news-unread"] })
    },
  })
}

export function useRefreshAiNews() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (source?: string) => refreshAiNews(source),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ai-news"] })
      queryClient.invalidateQueries({ queryKey: ["ai-news-sources"] })
      queryClient.invalidateQueries({ queryKey: ["ai-news-unread"] })
    },
  })
}
