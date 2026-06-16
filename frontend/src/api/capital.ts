/** Capital management API client. */

import client from "./client"

export interface CapitalTransaction {
  id: string
  type: string
  amount: number
  balance_after: number
  trade_id: string | null
  symbol: string | null
  description: string
  created_at: string
}

export interface PositionCapital {
  symbol: string
  stock_name: string
  shares: number
  cost_price: number
  market_value: number
  cost_basis: number
}

export interface CapitalBreakdown {
  available_cash: number
  position_value: number
  total_assets: number
  utilization_rate: number
  positions: PositionCapital[]
  has_initial_deposit: boolean
}

export interface CapitalHistoryResponse {
  transactions: CapitalTransaction[]
  total: number
}

/** Get full capital breakdown (cash + positions). */
export async function getCapitalBalance(): Promise<CapitalBreakdown> {
  const { data } = await client.get<CapitalBreakdown>("/capital/balance")
  return data
}

/** Deposit funds. */
export async function deposit(
  amount: number,
  description?: string,
): Promise<CapitalTransaction> {
  const { data } = await client.post<CapitalTransaction>("/capital/deposit", {
    amount,
    description: description ?? "",
  })
  return data
}

/** Withdraw funds. */
export async function withdraw(
  amount: number,
  description?: string,
): Promise<CapitalTransaction> {
  const { data } = await client.post<CapitalTransaction>("/capital/withdraw", {
    amount,
    description: description ?? "",
  })
  return data
}

/** Get capital transaction history. */
export async function getCapitalHistory(
  limit = 50,
  offset = 0,
  txType?: string,
): Promise<CapitalHistoryResponse> {
  const params: Record<string, string | number> = { limit, offset }
  if (txType) params.tx_type = txType
  const { data } = await client.get<CapitalHistoryResponse>(
    "/capital/history",
    { params },
  )
  return data
}
