import { Badge } from "@/components/ui/badge"
import { useLatestSignals } from "@/hooks/useBacktest"
import { TrendingUp, TrendingDown } from "lucide-react"

interface StrategyInsightBadgeProps {
  symbol: string
}

export function StrategyInsightBadge({ symbol }: StrategyInsightBadgeProps) {
  const { data: signals } = useLatestSignals(symbol)

  if (!signals || signals.length === 0) return null

  // Find dominant signal
  const buySignals = signals.filter((s) => s.signal === "buy")
  const sellSignals = signals.filter((s) => s.signal === "sell")

  let dominant: "buy" | "sell" | "hold" = "hold"
  if (buySignals.length > sellSignals.length) dominant = "buy"
  else if (sellSignals.length > buySignals.length) dominant = "sell"

  if (dominant === "hold") return null

  const Icon = dominant === "buy" ? TrendingUp : TrendingDown
  const label = dominant === "buy" ? "买入信号" : "卖出信号"
  const variant = dominant === "buy" ? "default" : "destructive"

  return (
    <Badge variant={variant} className="gap-1 text-[10px]">
      <Icon className="h-3 w-3" />
      {label}
    </Badge>
  )
}
