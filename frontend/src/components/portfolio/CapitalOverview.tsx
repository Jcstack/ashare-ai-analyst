/** Capital overview card — shows cash/positions/total with deposit/withdraw actions. */

import { useCallback, useEffect, useState } from "react"
import { Wallet, Plus, Minus, Loader2 } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { toast } from "sonner"
import {
  getCapitalBalance,
  deposit,
  withdraw,
  type CapitalBreakdown,
} from "@/api/capital"
import { getUserConfig, updateUserConfig } from "@/api/user-config"
import { CapitalHistory } from "./CapitalHistory"

const RISK_OPTIONS = [
  { value: "conservative", label: "保守" },
  { value: "moderate", label: "稳健" },
  { value: "aggressive", label: "积极" },
] as const

function formatMoney(n: number): string {
  if (n >= 1e8) return `${(n / 1e8).toFixed(2)}亿`
  if (n >= 1e4) return `${(n / 1e4).toFixed(2)}万`
  return n.toLocaleString("zh-CN", { minimumFractionDigits: 2 })
}

interface CapitalOverviewProps {
  /** Real-time portfolio market value from useRealtimeQuotes. Overrides backend cost-based value. */
  realtimePositionValue?: number
  /** Floating P&L = market value - cost basis. */
  floatingPnL?: number
  /** Floating P&L percentage. */
  floatingPnLPercent?: number
}

export function CapitalOverview({ realtimePositionValue, floatingPnL, floatingPnLPercent }: CapitalOverviewProps) {
  const [data, setData] = useState<CapitalBreakdown | null>(null)
  const [loading, setLoading] = useState(true)
  const [risk, setRisk] = useState("moderate")
  const [dialogType, setDialogType] = useState<"deposit" | "withdraw" | null>(
    null,
  )
  const [amount, setAmount] = useState("")
  const [submitting, setSubmitting] = useState(false)

  const fetchData = useCallback(async () => {
    try {
      const [balance, config] = await Promise.all([
        getCapitalBalance(),
        getUserConfig(),
      ])
      setData(balance)
      if (config.risk_tolerance) setRisk(config.risk_tolerance)
    } catch {
      // silent — component still renders
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const handleRiskChange = async (value: string) => {
    setRisk(value)
    try {
      await updateUserConfig({ risk_tolerance: value })
    } catch {
      toast.error("保存风险偏好失败")
    }
  }

  const handleSubmit = async () => {
    const num = parseFloat(amount)
    if (!num || num <= 0) {
      toast.error("请输入有效金额")
      return
    }
    setSubmitting(true)
    try {
      if (dialogType === "deposit") {
        await deposit(num)
        toast.success(`已增资 ¥${formatMoney(num)}`)
      } else {
        await withdraw(num)
        toast.success(`已减资 ¥${formatMoney(num)}`)
      }
      setDialogType(null)
      setAmount("")
      await fetchData()
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : "操作失败"
      toast.error(msg)
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <Card>
        <CardContent className="py-8 flex items-center justify-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          加载账户信息...
        </CardContent>
      </Card>
    )
  }

  // First-time setup — no initial deposit
  if (!data?.has_initial_deposit) {
    return (
      <Card>
        <CardHeader className="py-3 px-4">
          <div className="flex items-center gap-2">
            <Wallet className="h-4 w-4 text-accent-primary" />
            <CardTitle className="text-title">初始资金设置</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-4 px-4 pb-4">
          <p className="text-sm text-muted-foreground">
            设置您的模拟初始资金，AI
            将据此计算买入建议的仓位和股数。
          </p>
          <div className="flex items-center gap-2">
            <input
              type="number"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="如 500000"
              className="h-9 w-48 rounded-md border bg-transparent px-3 text-sm focus:outline-none focus:ring-1 focus:ring-accent-primary"
            />
            <span className="text-sm text-muted-foreground">元</span>
          </div>
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">风险偏好</p>
            <div className="flex gap-2">
              {RISK_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => handleRiskChange(opt.value)}
                  className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                    risk === opt.value
                      ? "border-accent-primary bg-accent-primary/10 text-accent-primary"
                      : "text-muted-foreground hover:bg-bg-hover"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
          <Button
            size="sm"
            disabled={submitting || !amount}
            onClick={async () => {
              const num = parseFloat(amount)
              if (!num || num <= 0) {
                toast.error("请输入有效金额")
                return
              }
              setSubmitting(true)
              try {
                await deposit(num)
                toast.success("初始资金已设置")
                setAmount("")
                await fetchData()
              } catch {
                toast.error("设置失败")
              } finally {
                setSubmitting(false)
              }
            }}
          >
            {submitting ? "设置中..." : "确认设置"}
          </Button>
        </CardContent>
      </Card>
    )
  }

  // Normal view — show breakdown
  // Use real-time position value from frontend when available (fixes I-007)
  const positionValue = realtimePositionValue ?? data.position_value
  const totalAssets = data.available_cash + positionValue

  const pnl = floatingPnL ?? 0
  const pnlPct = floatingPnLPercent ?? 0
  const pnlSign = pnl >= 0 ? "+" : ""
  const pnlColor = pnl > 0 ? "var(--color-market-up)" : pnl < 0 ? "var(--color-market-down)" : undefined

  const stats = [
    {
      label: "总资产",
      value: `¥${formatMoney(totalAssets)}`,
      color: undefined as string | undefined,
    },
    {
      label: "可用现金",
      value: `¥${formatMoney(data.available_cash)}`,
      color: undefined as string | undefined,
    },
    {
      label: "持仓市值",
      value: `¥${formatMoney(positionValue)}`,
      color: undefined as string | undefined,
    },
    {
      label: "浮动盈亏",
      value: `${pnlSign}¥${formatMoney(Math.abs(pnl))} (${pnlSign}${pnlPct.toFixed(2)}%)`,
      color: pnlColor,
    },
  ]

  return (
    <>
      <Card>
        <CardHeader className="py-3 px-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Wallet className="h-4 w-4 text-accent-primary" />
              <CardTitle className="text-title">账户总览</CardTitle>
            </div>
            <div className="flex items-center gap-2">
              {/* Risk preference pills */}
              <div className="flex gap-1 mr-2">
                {RISK_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => handleRiskChange(opt.value)}
                    className={`rounded-full border px-2 py-0.5 text-xs transition-colors ${
                      risk === opt.value
                        ? "border-accent-primary bg-accent-primary/10 text-accent-primary"
                        : "text-muted-foreground hover:bg-bg-hover"
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
              <Button
                variant="outline"
                size="sm"
                className="gap-1 h-7 text-xs"
                onClick={() => {
                  setDialogType("deposit")
                  setAmount("")
                }}
              >
                <Plus className="h-3 w-3" />
                增资
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="gap-1 h-7 text-xs"
                onClick={() => {
                  setDialogType("withdraw")
                  setAmount("")
                }}
              >
                <Minus className="h-3 w-3" />
                减资
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {stats.map((s) => (
              <div key={s.label}>
                <p className="text-xs text-muted-foreground">{s.label}</p>
                <p
                  className="text-lg font-bold mt-0.5 font-numeric"
                  style={s.color ? { color: s.color } : undefined}
                >
                  {s.value}
                </p>
              </div>
            ))}
          </div>
          {/* Transaction history (collapsed) */}
          <CapitalHistory />
        </CardContent>
      </Card>

      {/* Deposit / Withdraw dialog */}
      <Dialog
        open={dialogType !== null}
        onOpenChange={(open) => !open && setDialogType(null)}
      >
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>
              {dialogType === "deposit" ? "增资" : "减资"}
            </DialogTitle>
            <DialogDescription>
              {dialogType === "deposit"
                ? "向模拟账户增加资金"
                : `可用余额 ¥${formatMoney(data.available_cash)}`}
            </DialogDescription>
          </DialogHeader>
          <div className="flex items-center gap-2 py-4">
            <input
              type="number"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="金额"
              autoFocus
              className="h-9 flex-1 rounded-md border bg-transparent px-3 text-sm focus:outline-none focus:ring-1 focus:ring-accent-primary"
            />
            <span className="text-sm text-muted-foreground">元</span>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setDialogType(null)}
            >
              取消
            </Button>
            <Button size="sm" disabled={submitting} onClick={handleSubmit}>
              {submitting ? "处理中..." : "确认"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
