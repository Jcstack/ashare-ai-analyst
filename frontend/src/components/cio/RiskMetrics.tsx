/** Risk metrics panel — VaR, max drawdown, Sharpe ratio, win rate from equity curve data. */

import { Card, CardContent } from "@/components/ui/card"
import { useQuery } from "@tanstack/react-query"
import client from "@/api/client"
import { Loader2 } from "lucide-react"
import type { EquitySnapshot } from "@/types/cio-dashboard"

async function fetchEquityCurve(days: number): Promise<{ snapshots: EquitySnapshot[]; count: number }> {
  const { data } = await client.get("/intelligence/equity-curve", { params: { days } })
  return data
}

/** Calculate daily returns from snapshots. */
function dailyReturns(snapshots: EquitySnapshot[]): number[] {
  const returns: number[] = []
  for (let i = 1; i < snapshots.length; i++) {
    const prev = snapshots[i - 1].total_value
    if (prev > 0) {
      returns.push((snapshots[i].total_value - prev) / prev)
    }
  }
  return returns
}

/** Value at Risk (95%) — parametric, assumes normal distribution. */
function calcVaR95(returns: number[]): number {
  if (returns.length < 2) return 0
  const mean = returns.reduce((a, b) => a + b, 0) / returns.length
  const variance = returns.reduce((sum, r) => sum + (r - mean) ** 2, 0) / (returns.length - 1)
  const std = Math.sqrt(variance)
  // VaR95 = mean - 1.645 * std (left tail, reported as positive loss)
  return -(mean - 1.645 * std)
}

/** Max drawdown — largest peak-to-trough decline as a fraction. */
function calcMaxDrawdown(snapshots: EquitySnapshot[]): number {
  if (snapshots.length < 2) return 0
  let peak = snapshots[0].total_value
  let maxDd = 0
  for (const s of snapshots) {
    if (s.total_value > peak) peak = s.total_value
    const dd = (peak - s.total_value) / peak
    if (dd > maxDd) maxDd = dd
  }
  return maxDd
}

/** Annualized Sharpe ratio (risk-free rate = 0 for simplicity). */
function calcSharpe(returns: number[]): number {
  if (returns.length < 2) return 0
  const mean = returns.reduce((a, b) => a + b, 0) / returns.length
  const variance = returns.reduce((sum, r) => sum + (r - mean) ** 2, 0) / (returns.length - 1)
  const std = Math.sqrt(variance)
  if (std === 0) return 0
  return (mean / std) * Math.sqrt(252)
}

/** Win rate — fraction of days with positive return. */
function calcWinRate(returns: number[]): number {
  if (returns.length === 0) return 0
  const wins = returns.filter((r) => r > 0).length
  return wins / returns.length
}

/** Color class based on metric thresholds. */
function metricColor(id: string, value: number): string {
  switch (id) {
    case "var":
      if (value <= 0.02) return "text-market-up"
      if (value <= 0.05) return "text-yellow-500"
      return "text-market-down"
    case "drawdown":
      if (value <= 0.05) return "text-market-up"
      if (value <= 0.15) return "text-yellow-500"
      return "text-market-down"
    case "sharpe":
      if (value >= 1.5) return "text-market-up"
      if (value >= 0.5) return "text-yellow-500"
      return "text-market-down"
    case "winrate":
      if (value >= 0.55) return "text-market-up"
      if (value >= 0.45) return "text-yellow-500"
      return "text-market-down"
    default:
      return "text-muted-foreground"
  }
}

interface MetricItem {
  id: string
  label: string
  value: number
  format: (v: number) => string
}

export function RiskMetrics({ days = 90 }: { days?: number }) {
  const { data, isLoading } = useQuery({
    queryKey: ["intelligence", "equity-curve", days],
    queryFn: () => fetchEquityCurve(days),
    staleTime: 5 * 60 * 1000,
  })

  const snapshots = data?.snapshots ?? []

  if (isLoading) {
    return (
      <Card>
        <CardContent className="py-6 flex items-center justify-center text-xs text-muted-foreground gap-2">
          <Loader2 className="h-3 w-3 animate-spin" />
          计算风险指标...
        </CardContent>
      </Card>
    )
  }

  if (snapshots.length < 2) {
    return (
      <Card>
        <CardContent className="py-6 text-center text-xs text-muted-foreground">
          数据不足，需至少 2 日净值快照
        </CardContent>
      </Card>
    )
  }

  const returns = dailyReturns(snapshots)

  const metrics: MetricItem[] = [
    {
      id: "var",
      label: "VaR (95%)",
      value: calcVaR95(returns),
      format: (v) => `${(v * 100).toFixed(2)}%`,
    },
    {
      id: "drawdown",
      label: "最大回撤",
      value: calcMaxDrawdown(snapshots),
      format: (v) => `${(v * 100).toFixed(2)}%`,
    },
    {
      id: "sharpe",
      label: "Sharpe",
      value: calcSharpe(returns),
      format: (v) => v.toFixed(2),
    },
    {
      id: "winrate",
      label: "胜率",
      value: calcWinRate(returns),
      format: (v) => `${(v * 100).toFixed(1)}%`,
    },
  ]

  return (
    <Card>
      <CardContent className="py-4 px-5 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-caption font-medium">风险指标</span>
          <span className="text-[10px] text-muted-foreground">{snapshots.length} 日</span>
        </div>
        <div className="grid grid-cols-2 gap-3">
          {metrics.map((m) => (
            <div key={m.id} className="rounded-md bg-muted/50 p-3 text-center space-y-1">
              <div className={`text-lg font-numeric font-semibold ${metricColor(m.id, m.value)}`}>
                {m.format(m.value)}
              </div>
              <div className="text-[10px] text-muted-foreground">{m.label}</div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
