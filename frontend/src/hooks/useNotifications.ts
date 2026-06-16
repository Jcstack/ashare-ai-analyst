import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import client from "@/api/client"

export interface NotificationItem {
  id: string
  type: "sentiment_shift" | "hot_entry" | "anomaly" | "market_overview" | "strategy_signal" | "system" | "market_status" | "holiday_preview" | "intel_report"
  title: string
  summary: string
  symbol: string | null
  timestamp: string
  read: boolean
  action?: string
  new_item_ids?: string[]
}

async function fetchNotifications(): Promise<NotificationItem[]> {
  const { data } = await client.get<NotificationItem[]>("/notifications/recent?limit=50")
  return data
}

async function fetchUnreadCount(): Promise<number> {
  const { data } = await client.get<{ count: number }>("/notifications/unread-count")
  return data.count
}

async function markRead(ids: string[]): Promise<void> {
  await client.post("/notifications/read", ids)
}

async function markAllRead(): Promise<void> {
  await client.post("/notifications/read-all")
}

async function purgeRead(): Promise<void> {
  await client.post("/notifications/purge-read")
}

export function useNotifications() {
  return useQuery({
    queryKey: ["notifications"],
    queryFn: fetchNotifications,
    refetchInterval: 30_000,
    staleTime: 15_000,
  })
}

export function useUnreadCount() {
  return useQuery({
    queryKey: ["notifications-unread"],
    queryFn: fetchUnreadCount,
    refetchInterval: 10_000,
    staleTime: 5_000,
  })
}

export function useMarkNotificationsRead() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: markRead,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] })
      queryClient.invalidateQueries({ queryKey: ["notifications-unread"] })
    },
  })
}

export function useMarkAllRead() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: markAllRead,
    onMutate: async () => {
      // Optimistically clear the badge immediately
      await queryClient.cancelQueries({ queryKey: ["notifications-unread"] })
      const previousCount = queryClient.getQueryData<number>(["notifications-unread"])
      queryClient.setQueryData<number>(["notifications-unread"], 0)

      // Optimistically mark all notifications as read in cache
      await queryClient.cancelQueries({ queryKey: ["notifications"] })
      const previousNotifications = queryClient.getQueryData<NotificationItem[]>(["notifications"])
      queryClient.setQueryData<NotificationItem[]>(["notifications"], (old) =>
        old?.map((n) => ({ ...n, read: true })) ?? []
      )

      return { previousCount, previousNotifications }
    },
    onError: (_err, _vars, context) => {
      if (context?.previousCount !== undefined) {
        queryClient.setQueryData(["notifications-unread"], context.previousCount)
      }
      if (context?.previousNotifications) {
        queryClient.setQueryData(["notifications"], context.previousNotifications)
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] })
      queryClient.invalidateQueries({ queryKey: ["notifications-unread"] })
    },
  })
}

export function usePurgeRead() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: purgeRead,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] })
      queryClient.invalidateQueries({ queryKey: ["notifications-unread"] })
    },
  })
}
