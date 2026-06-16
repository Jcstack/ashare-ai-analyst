import client from "./client"
import type {
  SchedulerStatus,
  SchedulePlansResult,
  CalendarResult,
  SentinelConfig,
} from "@/types/scheduler"
import type { ApiResponse } from "@/types/admin"

export async function fetchSchedulerStatus(): Promise<SchedulerStatus> {
  const { data } = await client.get<SchedulerStatus>("/scheduler/status")
  return data
}

export async function fetchSchedulePlans(): Promise<SchedulePlansResult> {
  const { data } = await client.get<SchedulePlansResult>("/scheduler/plans")
  return data
}

export async function updateSchedulePlan(
  plan: string,
  tasks: Record<string, boolean>,
): Promise<ApiResponse> {
  const { data } = await client.put<ApiResponse>(`/scheduler/plans/${plan}`, { tasks })
  return data
}

export async function setScheduleOverride(profile: string | null): Promise<ApiResponse> {
  const { data } = await client.post<ApiResponse>("/scheduler/override", { profile })
  return data
}

export async function fetchSchedulerCalendar(days = 30): Promise<CalendarResult> {
  const { data } = await client.get<CalendarResult>(`/scheduler/calendar?days=${days}`)
  return data
}

export async function fetchSentinelConfig(): Promise<SentinelConfig> {
  const { data } = await client.get<SentinelConfig>("/scheduler/sentinel-config")
  return data
}

export async function updateSentinelConfig(config: Partial<SentinelConfig>): Promise<ApiResponse> {
  const { data } = await client.put<ApiResponse>("/scheduler/sentinel-config", config)
  return data
}
