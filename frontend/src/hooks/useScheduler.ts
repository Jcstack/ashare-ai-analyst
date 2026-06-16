import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import {
  fetchSchedulerStatus,
  fetchSchedulePlans,
  updateSchedulePlan,
  setScheduleOverride,
  fetchSchedulerCalendar,
  fetchSentinelConfig,
  updateSentinelConfig,
} from "@/api/scheduler"

export function useSchedulerStatus() {
  return useQuery({
    queryKey: ["scheduler-status"],
    queryFn: fetchSchedulerStatus,
    staleTime: 30_000,
    refetchInterval: 60_000,
  })
}

export function useSchedulePlans() {
  return useQuery({
    queryKey: ["schedule-plans"],
    queryFn: fetchSchedulePlans,
    staleTime: 5 * 60_000,
  })
}

export function useUpdateSchedulePlan() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ plan, tasks }: { plan: string; tasks: Record<string, boolean> }) =>
      updateSchedulePlan(plan, tasks),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["schedule-plans"] })
    },
  })
}

export function useScheduleOverride() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (profile: string | null) => setScheduleOverride(profile),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scheduler-status"] })
    },
  })
}

export function useSchedulerCalendar(days = 30) {
  return useQuery({
    queryKey: ["scheduler-calendar", days],
    queryFn: () => fetchSchedulerCalendar(days),
    staleTime: 5 * 60_000,
  })
}

export function useSentinelConfig() {
  return useQuery({
    queryKey: ["sentinel-config"],
    queryFn: fetchSentinelConfig,
    staleTime: 5 * 60_000,
  })
}

export function useUpdateSentinelConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: updateSentinelConfig,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sentinel-config"] })
    },
  })
}
