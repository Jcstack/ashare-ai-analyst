/** API client for stock recommendation endpoints. */

import client from "./client"
import type {
  RecommendationListResponse,
  Recommendation,
  StylesResponse,
  InvestmentStyleConfig,
  PerformanceStats,
  RefreshResponse,
  RefreshRunStatus,
} from "@/types/recommendation"

export async function fetchRecommendations(params?: {
  style?: string
  session?: string
  limit?: number
}): Promise<RecommendationListResponse> {
  const { data } = await client.get<RecommendationListResponse>("/recommendations", {
    params,
  })
  return data
}

export async function fetchTodayRecommendations(
  style?: string
): Promise<RecommendationListResponse> {
  const { data } = await client.get<RecommendationListResponse>(
    "/recommendations/today",
    { params: style ? { style } : undefined }
  )
  return data
}

export async function fetchRecommendation(recId: string): Promise<Recommendation> {
  const { data } = await client.get<Recommendation>(`/recommendations/${recId}`)
  return data
}

export async function dismissRecommendation(
  recId: string
): Promise<{ success: boolean }> {
  const { data } = await client.post<{ success: boolean }>(
    `/recommendations/${recId}/dismiss`
  )
  return data
}

export async function fetchRecommendationCount(): Promise<{ count: number }> {
  const { data } = await client.get<{ count: number }>("/recommendations/count")
  return data
}

export async function fetchStyles(): Promise<StylesResponse> {
  const { data } = await client.get<StylesResponse>("/recommendations/styles")
  return data
}

export async function fetchPreferences(): Promise<InvestmentStyleConfig> {
  const { data } = await client.get<InvestmentStyleConfig>(
    "/recommendations/preferences"
  )
  return data
}

export async function updatePreferences(
  config: Partial<InvestmentStyleConfig>
): Promise<InvestmentStyleConfig> {
  const { data } = await client.put<InvestmentStyleConfig>(
    "/recommendations/preferences",
    config
  )
  return data
}

export async function updateFullPreferences(
  config: InvestmentStyleConfig
): Promise<InvestmentStyleConfig> {
  const { data } = await client.put<InvestmentStyleConfig>(
    "/recommendations/preferences",
    config
  )
  return data
}

export async function fetchPerformance(params?: {
  style?: string
  session?: string
  days?: number
}): Promise<PerformanceStats> {
  const { data } = await client.get<PerformanceStats>(
    "/recommendations/performance",
    { params }
  )
  return data
}

export async function refreshRecommendations(): Promise<RefreshResponse> {
  const { data } = await client.post<RefreshResponse>("/recommendations/refresh")
  return data
}

export async function fetchRefreshStatus(
  runId?: string
): Promise<RefreshRunStatus> {
  const { data } = await client.get<RefreshRunStatus>(
    "/recommendations/refresh/status",
    { params: runId ? { run_id: runId } : undefined }
  )
  return data
}
