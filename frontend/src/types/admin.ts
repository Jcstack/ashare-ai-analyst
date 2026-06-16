export interface ApiKeyInfo {
  provider: string
  label: string
  masked_key?: string
  status?: string
  expires_at?: string
  created_at?: string
}

export interface AddKeyRequest {
  provider: string
  key: string
  label: string
  expires_at?: string
}

export interface UsagePeriodSummary {
  total_calls?: number
  total_cost_usd?: number
}

export interface UsageDashboard {
  today?: UsagePeriodSummary
  total_cost_usd?: number
  period_days: number
  providers?: Record<string, unknown>
}

export interface RoutingConfig {
  available_providers: string[]
  strategies: string[]
}

export interface UpdateRoutingRequest {
  strategy: string
}

export interface BalanceInfo {
  provider: string
  status: string
  balance?: number
  message?: string
}

export interface ApiResponse {
  status: string
  message?: string
  data?: Record<string, unknown>
}
