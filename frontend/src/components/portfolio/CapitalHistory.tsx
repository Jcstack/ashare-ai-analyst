/** Capital transaction history — collapsible list. */

import { useEffect, useState } from "react"
import { formatTime } from "@/lib/formatters"
import { ChevronDown, ChevronRight, ArrowDownLeft, ArrowUpRight, RefreshCw } from "lucide-react"
import { getCapitalHistory, type CapitalTransaction } from "@/api/capital"

const TYPE_CONFIG: Record<string, { icon: typeof ArrowDownLeft; color: string; label: string }> = {
  initial_deposit: { icon: ArrowDownLeft, color: "text-green-500", label: "初始入金" },
  deposit: { icon: ArrowDownLeft, color: "text-green-500", label: "增资" },
  withdrawal: { icon: ArrowUpRight, color: "text-red-500", label: "减资" },
  trade_buy: { icon: RefreshCw, color: "text-red-500", label: "买入" },
  trade_sell: { icon: RefreshCw, color: "text-green-500", label: "卖出" },
}


export function CapitalHistory() {
  const [open, setOpen] = useState(false)
  const [transactions, setTransactions] = useState<CapitalTransaction[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open) return
    setLoading(true)
    getCapitalHistory(20)
      .then((res) => setTransactions(res.transactions))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [open])

  return (
    <div className="mt-3 border-t pt-3">
      <button
        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
        onClick={() => setOpen(!open)}
      >
        {open ? (
          <ChevronDown className="h-3 w-3" />
        ) : (
          <ChevronRight className="h-3 w-3" />
        )}
        资金流水
      </button>

      {open && (
        <div className="mt-2 space-y-1 max-h-64 overflow-y-auto">
          {loading && (
            <p className="text-xs text-muted-foreground py-2">加载中...</p>
          )}
          {!loading && transactions.length === 0 && (
            <p className="text-xs text-muted-foreground py-2">暂无记录</p>
          )}
          {transactions.map((tx) => {
            const cfg = TYPE_CONFIG[tx.type] ?? TYPE_CONFIG.deposit
            const Icon = cfg.icon
            return (
              <div
                key={tx.id}
                className="flex items-center gap-2 py-1.5 text-xs"
              >
                <Icon className={`h-3.5 w-3.5 shrink-0 ${cfg.color}`} />
                <span className="flex-1 truncate text-muted-foreground">
                  {tx.description || cfg.label}
                </span>
                <span
                  className={`font-numeric font-medium ${
                    tx.amount >= 0 ? "text-green-500" : "text-red-500"
                  }`}
                >
                  {tx.amount >= 0 ? "+" : ""}
                  {tx.amount.toLocaleString("zh-CN", {
                    minimumFractionDigits: 2,
                  })}
                </span>
                <span className="text-muted-foreground/60 w-24 text-right shrink-0">
                  余 ¥
                  {tx.balance_after.toLocaleString("zh-CN", {
                    minimumFractionDigits: 2,
                  })}
                </span>
                <span className="text-muted-foreground/40 w-20 text-right shrink-0">
                  {formatTime(tx.created_at)}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
