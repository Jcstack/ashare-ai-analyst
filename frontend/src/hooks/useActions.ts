import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import {
  fetchBootstrap,
  fetchActionQueue,
  confirmAction,
  rejectAction,
  recordFill,
  fetchTheses,
  fetchReview,
} from "@/api/actions"

// ---------------------------------------------------------------------------
// Bootstrap — single call to hydrate the Control Tower
// ---------------------------------------------------------------------------

export function useBootstrap() {
  return useQuery({
    queryKey: ["control-tower-bootstrap"],
    queryFn: fetchBootstrap,
    staleTime: 30_000,
    refetchInterval: 60_000,
    retry: 2,
  })
}

// ---------------------------------------------------------------------------
// Action Queue
// ---------------------------------------------------------------------------

export function useActionQueue() {
  return useQuery({
    queryKey: ["action-queue"],
    queryFn: fetchActionQueue,
    staleTime: 15_000,
    refetchInterval: 30_000,
  })
}

export function useConfirmAction() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (actionId: string) => confirmAction(actionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["action-queue"] })
      queryClient.invalidateQueries({ queryKey: ["control-tower-bootstrap"] })
    },
  })
}

export function useRejectAction() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (actionId: string) => rejectAction(actionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["action-queue"] })
      queryClient.invalidateQueries({ queryKey: ["control-tower-bootstrap"] })
    },
  })
}

export function useRecordFill() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ actionId, fill }: { actionId: string; fill: { price: number; shares: number } }) =>
      recordFill(actionId, fill),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["action-queue"] })
      queryClient.invalidateQueries({ queryKey: ["control-tower-bootstrap"] })
    },
  })
}

// ---------------------------------------------------------------------------
// Theses
// ---------------------------------------------------------------------------

export function useTheses() {
  return useQuery({
    queryKey: ["theses"],
    queryFn: fetchTheses,
    staleTime: 60_000,
    refetchInterval: 120_000,
  })
}

// ---------------------------------------------------------------------------
// Review
// ---------------------------------------------------------------------------

export function useReview(date?: string) {
  return useQuery({
    queryKey: ["review", date],
    queryFn: () => fetchReview(date),
    staleTime: 5 * 60_000,
  })
}
