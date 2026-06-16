/** Trade hooks — React Query mutations for manual trade execution. */

import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { recordManualTrade } from "@/api/trade"
import type { ManualTradeParams } from "@/api/trade"

const ACTION_LABELS: Record<string, string> = {
  buy: "买入",
  sell: "卖出",
  add: "加仓",
  reduce: "减仓",
}

/** Mutation hook for recording a manual trade (buy/sell/add/reduce). */
export function useManualTrade() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: (params: ManualTradeParams) => recordManualTrade(params),
    onSuccess: (_data, variables) => {
      const label = ACTION_LABELS[variables.action] ?? variables.action
      toast.success(`${label} ${variables.stock_name} 成功`)
      qc.invalidateQueries({ queryKey: ["portfolio"] })
      qc.invalidateQueries({ queryKey: ["capital"] })
      qc.invalidateQueries({ queryKey: ["trades"] })
    },
    onError: (error: unknown) => {
      // Backend returns Chinese messages for 409 MARKET_CLOSED / 400 validation errors
      const msg =
        (error as { response?: { data?: { detail?: { message?: string } | string } } })
          ?.response?.data?.detail
      const text = typeof msg === "string" ? msg : (msg as { message?: string })?.message
      toast.error(text || "交易失败，请稍后重试")
    },
  })
}
