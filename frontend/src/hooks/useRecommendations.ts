/** React Query hooks for stock recommendations. */

import { useRef, useEffect } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import {
  fetchRecommendations,
  fetchTodayRecommendations,
  fetchRecommendation,
  dismissRecommendation,
  fetchRecommendationCount,
  fetchStyles,
  fetchPreferences,
  updateFullPreferences,
  fetchPerformance,
  refreshRecommendations,
  fetchRefreshStatus,
} from "@/api/recommendations"
import type { InvestmentStyleConfig } from "@/types/recommendation"

export function useRecommendations(params?: {
  style?: string
  session?: string
  limit?: number
}) {
  return useQuery({
    queryKey: ["recommendations", params],
    queryFn: () => fetchRecommendations(params),
    staleTime: 15_000,
    refetchInterval: 30_000,
  })
}

export function useTodayRecommendations(style?: string) {
  return useQuery({
    queryKey: ["recommendations-today", style],
    queryFn: () => fetchTodayRecommendations(style),
    staleTime: 15_000,
    refetchInterval: 30_000,
  })
}

export function useRecommendationDetail(recId: string | null) {
  return useQuery({
    queryKey: ["recommendation-detail", recId],
    queryFn: () => fetchRecommendation(recId!),
    enabled: !!recId,
    staleTime: 15_000,
  })
}

export function useDismissRecommendation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: dismissRecommendation,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["recommendations"] })
      queryClient.invalidateQueries({ queryKey: ["recommendations-today"] })
    },
  })
}

export function useRecommendationCount() {
  return useQuery({
    queryKey: ["recommendation-count"],
    queryFn: fetchRecommendationCount,
    staleTime: 60_000,
    refetchInterval: 120_000,
  })
}

export function useStyles() {
  return useQuery({
    queryKey: ["recommendation-styles"],
    queryFn: fetchStyles,
    staleTime: 300_000,
  })
}

export function usePreferences() {
  return useQuery({
    queryKey: ["recommendation-preferences"],
    queryFn: fetchPreferences,
    staleTime: 60_000,
  })
}

export function useUpdateFullPreferences() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (config: InvestmentStyleConfig) => updateFullPreferences(config),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["recommendation-preferences"] })
    },
  })
}

export function usePerformance(params?: {
  style?: string
  session?: string
  days?: number
}) {
  return useQuery({
    queryKey: ["recommendation-performance", params],
    queryFn: () => fetchPerformance(params),
    staleTime: 300_000,
  })
}

export function useRefreshRecommendations() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: refreshRecommendations,
    onSuccess: (data) => {
      // For non-accepted responses (ok, cooldown, skipped), refresh immediately
      if (data.status !== "accepted") {
        queryClient.invalidateQueries({ queryKey: ["recommendations"] })
        queryClient.invalidateQueries({ queryKey: ["recommendations-today"] })
        queryClient.invalidateQueries({ queryKey: ["recommendation-count"] })
      }
      // For "accepted", the page will poll via useRefreshStatus
    },
  })
}

const REFRESH_POLL_TIMEOUT = 600_000 // 10 minutes max polling (Celery can take ~9min)

export function useRefreshStatus(runId: string | null) {
  const startRef = useRef(Date.now())
  const timedOutRef = useRef(false)

  useEffect(() => {
    if (runId) {
      startRef.current = Date.now()
      timedOutRef.current = false
    }
  }, [runId])

  return useQuery({
    queryKey: ["refresh-status", runId],
    queryFn: () => fetchRefreshStatus(runId!),
    enabled: !!runId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status === "running") {
        if (Date.now() - startRef.current > REFRESH_POLL_TIMEOUT) {
          timedOutRef.current = true
          return false
        }
        return 3_000
      }
      return false // stop polling on terminal state
    },
    // When polling stops due to timeout, override status so the page clears loading
    select: (data) => {
      if (timedOutRef.current && data.status === "running") {
        return { ...data, status: "failed" as const, error: "客户端轮询超时" }
      }
      return data
    },
    staleTime: 0,
  })
}
