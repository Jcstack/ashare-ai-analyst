/** User configuration API client. */

import client from "./client"
import type { UserFollows, NotificationPrefs } from "@/types/intelligence"

export async function getUserConfig(): Promise<Record<string, string>> {
  const { data } = await client.get<{ config: Record<string, string> }>(
    "/user/config",
  )
  return data.config
}

export async function updateUserConfig(
  config: Record<string, string>,
): Promise<Record<string, string>> {
  const { data } = await client.put<{ config: Record<string, string> }>(
    "/user/config",
    { config },
  )
  return data.config
}

// ─── v20.0 User Follows ──────────────────────────────────────────────────────

export async function getUserFollows(): Promise<UserFollows> {
  const { data } = await client.get<UserFollows>("/user/follows")
  return data
}

export async function updateUserFollows(follows: Partial<UserFollows>): Promise<UserFollows> {
  const { data } = await client.put<UserFollows>("/user/follows", follows)
  return data
}

// ─── v20.0 Notification Preferences ──────────────────────────────────────────

export async function getNotificationPrefs(): Promise<NotificationPrefs> {
  const { data } = await client.get<NotificationPrefs>("/user/notification-prefs")
  return data
}

export async function updateNotificationPrefs(
  prefs: Partial<NotificationPrefs>,
): Promise<NotificationPrefs> {
  const { data } = await client.put<NotificationPrefs>("/user/notification-prefs", prefs)
  return data
}
