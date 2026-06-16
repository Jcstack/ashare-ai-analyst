/** API client for Intel Reports endpoints. */

import client from "./client"
import type { IntelReport, ReportListParams, ReportListResponse } from "@/types/intel-report"

export async function fetchReports(params?: ReportListParams): Promise<ReportListResponse> {
  const { data } = await client.get<ReportListResponse>("/reports", { params })
  return data
}

export async function fetchReport(id: string): Promise<IntelReport> {
  const { data } = await client.get<IntelReport>(`/reports/${id}`)
  return data
}

export async function fetchReportUnreadCount(): Promise<number> {
  const { data } = await client.get<{ count: number }>("/reports/unread-count")
  return data.count
}

export async function markReportRead(id: string): Promise<void> {
  await client.post(`/reports/${id}/read`)
}

export async function deleteReport(id: string): Promise<void> {
  await client.delete(`/reports/${id}`)
}

export interface ChatFromReportResult {
  thread_id: string
  initial_message: string
}

export async function createChatFromReport(id: string): Promise<ChatFromReportResult> {
  const { data } = await client.post<ChatFromReportResult>(`/reports/${id}/chat`)
  return data
}
