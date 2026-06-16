import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { TrendingUp, TrendingDown, Minus } from "lucide-react"
import { useLatestSignals } from "@/hooks/useBacktest"

interface StrategySignalCardProps {
  symbol: string
}

const SIGNAL_CONFIG = {
  buy: { icon: TrendingUp, color: "text-[var(--color-market-down)]", bg: "bg-[var(--color-market-down)]/10", label: "买入" },
  sell: { icon: TrendingDown, color: "text-[var(--color-market-up)]", bg: "bg-[var(--color-market-up)]/10", label: "卖出" },
  hold: { icon: Minus, color: "text-muted-foreground", bg: "bg-muted", label: "持有" },
}

export function StrategySignalCard({ symbol }: StrategySignalCardProps) {
  const { data: signals, isLoading } = useLatestSignals(symbol)

  if (isLoading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">策略信号</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </CardContent>
      </Card>
    )
  }

  if (!signals || signals.length === 0) return null

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">策略信号</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {signals.map((sig) => {
          const config = SIGNAL_CONFIG[sig.signal] ?? SIGNAL_CONFIG.hold
          const Icon = config.icon
          return (
            <div key={sig.strategy_key} className="flex items-center justify-between rounded-lg border p-2">
              <div className="flex items-center gap-2">
                <div className={`rounded-md p-1 ${config.bg}`}>
                  <Icon className={`h-3.5 w-3.5 ${config.color}`} />
                </div>
                <div>
                  <p className="text-xs font-medium">{sig.strategy_name}</p>
                  {sig.reason && <p className="text-[10px] text-muted-foreground truncate max-w-[180px]">{sig.reason}</p>}
                </div>
              </div>
              <div className="flex items-center gap-2">
                {/* Strength bar */}
                <div className="w-12 h-1.5 bg-muted rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all"
                    style={{
                      width: `${sig.strength * 100}%`,
                      backgroundColor: sig.signal === "buy" ? "#EF5350" : sig.signal === "sell" ? "#26A69A" : "#94a3b8",
                    }}
                  />
                </div>
                <span className={`text-xs font-medium ${config.color}`}>{config.label}</span>
              </div>
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}
