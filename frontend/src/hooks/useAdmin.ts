import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { getKeys, addKey, removeKey, getUsage, getBalance, getRouting, updateRouting } from "@/api/admin"
import type { AddKeyRequest, UpdateRoutingRequest } from "@/types/admin"

export function useKeys() {
  return useQuery({
    queryKey: ["admin-keys"],
    queryFn: getKeys,
  })
}

export function useAddKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (req: AddKeyRequest) => addKey(req),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-keys"] })
    },
  })
}

export function useRemoveKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ provider, label }: { provider: string; label: string }) =>
      removeKey(provider, label),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-keys"] })
    },
  })
}

export function useUsage() {
  return useQuery({
    queryKey: ["admin-usage"],
    queryFn: getUsage,
  })
}

export function useBalance() {
  return useQuery({
    queryKey: ["admin-balance"],
    queryFn: getBalance,
  })
}

export function useRouting() {
  return useQuery({
    queryKey: ["admin-routing"],
    queryFn: getRouting,
  })
}

export function useUpdateRouting() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (req: UpdateRoutingRequest) => updateRouting(req),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-routing"] })
    },
  })
}
