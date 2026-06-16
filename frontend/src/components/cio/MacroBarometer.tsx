/** Macro exposure barometer — shows portfolio sensitivity to 6 macro factors. */

import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import type { DashboardData } from "@/types/cio-dashboard"

const FACTOR_LABELS: Record<string, string> = {
  interest_rate: "利率",
  usd_index: "美元",
  oil_price: "原油",
  gold_price: "黄金",
  trade_tension: "贸易摩擦",
  liquidity: "流动性",
}

function BarSegment({ label, value }: { label: string; value: number }) {
  const pct = Math.abs(value) * 100
  const isPositive = value >= 0
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-16 text-muted-foreground shrink-0">{label}</span>
      <div className="flex-1 h-3 bg-muted rounded-full overflow-hidden relative">
        <div
          className={`absolute top-0 h-full rounded-full transition-all ${
            isPositive ? "bg-market-up/60 left-1/2" : "bg-market-down/60 right-1/2"
          }`}
          style={{ width: `${Math.min(pct, 50)}%` }}
        />
        <div className="absolute inset-y-0 left-1/2 w-px bg-border" />
      </div>
      <span
        className={`w-10 text-right font-numeric ${
          isPositive ? "text-market-up" : value < 0 ? "text-market-down" : "text-muted-foreground"
        }`}
      >
        {value > 0 ? "+" : ""}
        {value.toFixed(2)}
      </span>
    </div>
  )
}

interface Props {
  data: DashboardData
}

export function MacroBarometer({ data }: Props) {
  const { portfolio, black_swan } = data
  const exposure = portfolio.macro_exposure ?? {}
  const factors = Object.entries(exposure)

  const alertColor =
    black_swan.alert_level === "CRITICAL"
      ? "destructive"
      : black_swan.alert_level === "ELEVATED"
        ? "secondary"
        : "outline"

  return (
    <Card>
      <CardContent className="py-4 px-5 space-y-4">
        <div className="flex items-center justify-between">
          <span className="text-caption font-medium">宏观敏感度</span>
          <div className="flex items-center gap-2">
            <Badge variant={alertColor} className="text-[10px]">
              {black_swan.alert_level === "NONE" ? "正常" : black_swan.alert_level}
            </Badge>
            {portfolio.stressed_count > 0 && (
              <Badge variant="destructive" className="text-[10px]">
                {portfolio.stressed_count} 持仓承压
              </Badge>
            )}
          </div>
        </div>

        {factors.length > 0 ? (
          <div className="space-y-2">
            {factors.map(([key, val]) => (
              <BarSegment key={key} label={FACTOR_LABELS[key] ?? key} value={val} />
            ))}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">暂无宏观暴露数据</p>
        )}

        {black_swan.message && black_swan.alert_level !== "NONE" && (
          <p className="text-xs text-warning">{black_swan.message}</p>
        )}
      </CardContent>
    </Card>
  )
}
