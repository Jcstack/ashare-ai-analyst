/** Intelligence Hub API client — endpoints under /intelligence-hub. */

import client from "./client"
import type { FeedResponse, OverviewResponse, CategoryCount, InfoItem, FeedParams, SourceHealth, EventClustersResponse } from "@/types/info-hub"

export async function getFeed(params?: FeedParams): Promise<FeedResponse> {
  const { data } = await client.get<FeedResponse>("/intelligence-hub/feed", { params })
  return data
}

export async function getOverview(days?: number): Promise<OverviewResponse> {
  const { data } = await client.get<OverviewResponse>("/intelligence-hub/overview", {
    params: days ? { days } : undefined,
  })
  return data
}

export async function getCategories(days?: number): Promise<CategoryCount[]> {
  const { data } = await client.get<CategoryCount[]>("/intelligence-hub/categories", {
    params: days ? { days } : undefined,
  })
  return data
}

export async function getItem(itemId: string): Promise<InfoItem> {
  const { data } = await client.get<InfoItem>(`/intelligence-hub/item/${itemId}`)
  return data
}

export async function toggleBookmark(itemId: string): Promise<{ item_id: string; is_bookmarked: boolean }> {
  const { data } = await client.post<{ item_id: string; is_bookmarked: boolean }>(
    `/intelligence-hub/item/${itemId}/bookmark`,
  )
  return data
}

export async function markRead(itemId: string): Promise<{ item_id: string; is_read: boolean }> {
  const { data } = await client.post<{ item_id: string; is_read: boolean }>(
    `/intelligence-hub/item/${itemId}/read`,
  )
  return data
}

export async function getSourcesHealth(): Promise<SourceHealth[]> {
  const { data } = await client.get<SourceHealth[]>("/intelligence-hub/sources/health")
  return data
}

export interface RefreshResponse {
  new_items: number
  new_item_ids: string[]
  status: string
}

export async function refreshFeed(): Promise<RefreshResponse> {
  const { data } = await client.post<RefreshResponse>("/intelligence-hub/refresh")
  return data
}

export async function getEventClusters(days?: number, minSources?: number): Promise<EventClustersResponse> {
  const params: Record<string, number> = {}
  if (days) params.days = days
  if (minSources) params.min_sources = minSources
  const { data } = await client.get<EventClustersResponse>("/intelligence-hub/events/clusters", { params })
  return data
}
