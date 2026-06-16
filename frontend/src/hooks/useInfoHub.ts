/** React Query hooks for v21.0 Intelligence Hub endpoints. */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { getFeed, getOverview, getCategories, toggleBookmark, markRead, refreshFeed, getSourcesHealth, getEventClusters } from "@/api/info-hub"
import { useInfoHubStore } from "@/stores/infoHubStore"
import type { FeedParams } from "@/types/info-hub"

const FEED_STALE = 30 * 1000
const FEED_REFETCH = 2 * 60 * 1000 // 2-minute auto-poll
const OVERVIEW_STALE = 60 * 1000

export function useInfoFeed(params?: FeedParams) {
  return useQuery({
    queryKey: ["info-hub", "feed", params],
    queryFn: () => getFeed(params),
    staleTime: FEED_STALE,
    refetchInterval: FEED_REFETCH,
  })
}

export function useInfoOverview(days?: number) {
  return useQuery({
    queryKey: ["info-hub", "overview", days],
    queryFn: () => getOverview(days),
    staleTime: OVERVIEW_STALE,
  })
}

export function useInfoCategories(days?: number) {
  return useQuery({
    queryKey: ["info-hub", "categories", days],
    queryFn: () => getCategories(days),
    staleTime: OVERVIEW_STALE,
  })
}

export function useToggleBookmark() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (itemId: string) => toggleBookmark(itemId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["info-hub"] })
    },
  })
}

export function useMarkRead() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (itemId: string) => markRead(itemId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["info-hub"] })
    },
  })
}

export function useRefreshFeed() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => refreshFeed(),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["info-hub"] })
      queryClient.invalidateQueries({ queryKey: ["notifications"] })
      queryClient.invalidateQueries({ queryKey: ["notifications-unread"] })

      // Track new item IDs for "新" badge display
      if (data.new_item_ids?.length) {
        useInfoHubStore.getState().setNewItemIds(new Set(data.new_item_ids))
        // Auto-clear after 5 minutes
        setTimeout(() => useInfoHubStore.getState().clearNewItemIds(), 5 * 60 * 1000)
      }
    },
  })
}

export function useSourcesHealth() {
  return useQuery({
    queryKey: ["info-hub", "sources-health"],
    queryFn: () => getSourcesHealth(),
    staleTime: OVERVIEW_STALE,
  })
}

export function useEventClusters(days?: number, minSources?: number) {
  return useQuery({
    queryKey: ["info-hub", "event-clusters", days, minSources],
    queryFn: () => getEventClusters(days, minSources),
    staleTime: OVERVIEW_STALE,
  })
}
