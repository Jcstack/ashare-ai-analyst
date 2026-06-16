import client from "./client"
import type { ApiKeyInfo, AddKeyRequest, UsageDashboard, RoutingConfig, BalanceInfo, ApiResponse, UpdateRoutingRequest } from "@/types/admin"

export async function getKeys(): Promise<ApiKeyInfo[]> {
  const { data } = await client.get<ApiKeyInfo[]>("/admin/keys")
  return data
}

export async function addKey(req: AddKeyRequest): Promise<ApiResponse> {
  const { data } = await client.post<ApiResponse>("/admin/keys", req)
  return data
}

export async function removeKey(provider: string, label: string): Promise<ApiResponse> {
  const { data } = await client.delete<ApiResponse>(`/admin/keys/${provider}/${label}`)
  return data
}

export async function getUsage(): Promise<UsageDashboard> {
  const { data } = await client.get<UsageDashboard>("/admin/usage")
  return data
}

export async function getBalance(): Promise<BalanceInfo[]> {
  const { data } = await client.get<BalanceInfo[]>("/admin/balance")
  return data
}

export async function getRouting(): Promise<RoutingConfig> {
  const { data } = await client.get<RoutingConfig>("/admin/routing")
  return data
}

export async function updateRouting(req: UpdateRoutingRequest): Promise<ApiResponse> {
  const { data } = await client.post<ApiResponse>("/admin/routing", req)
  return data
}

export async function updateConfig(section: string, params: Record<string, unknown>): Promise<ApiResponse> {
  const { data } = await client.post<ApiResponse>(`/admin/config/${section}`, { params })
  return data
}
