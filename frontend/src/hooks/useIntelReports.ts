/** React Query hooks for Intel Reports. */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import {
  fetchReports,
  fetchReport,
  fetchReportUnreadCount,
  markReportRead,
  deleteReport,
  createChatFromReport,
} from "@/api/intel-reports"
import type { ReportListParams } from "@/types/intel-report"

export function useReports(params?: ReportListParams) {
  return useQuery({
    queryKey: ["intel-reports", params],
    queryFn: () => fetchReports(params),
    staleTime: 30_000,
    refetchInterval: 60_000,
  })
}

export function useReport(id: string | null) {
  return useQuery({
    queryKey: ["intel-report", id],
    queryFn: () => fetchReport(id!),
    enabled: !!id,
    staleTime: 60_000,
  })
}

export function useReportUnreadCount() {
  return useQuery({
    queryKey: ["intel-reports-unread"],
    queryFn: fetchReportUnreadCount,
    refetchInterval: 15_000,
    staleTime: 10_000,
  })
}

export function useMarkReportRead() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: markReportRead,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["intel-reports"] })
      queryClient.invalidateQueries({ queryKey: ["intel-reports-unread"] })
    },
  })
}

export function useDeleteReport() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteReport,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["intel-reports"] })
      queryClient.invalidateQueries({ queryKey: ["intel-reports-unread"] })
    },
  })
}

export function useCreateChatFromReport() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createChatFromReport,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["intel-reports"] })
    },
  })
}

export type { ChatFromReportResult } from "@/api/intel-reports"
