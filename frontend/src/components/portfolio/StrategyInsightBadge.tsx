import { Badge } from "@/components/ui/badge"
import { useLatestSignals } from "@/hooks/useBacktest"
import { useLatestAgentSignal } from "@/hooks/useMessages"
import { TrendingUp, TrendingDown, Bot } from "lucide-react"

interface StrategyInsightBadgeProps {
  symbol: string
}

export function StrategyInsightBadge({ symbol }: StrategyInsightBadgeProps) {
  const { data: agentSignal } = useLatestAgentSignal(symbol)
  const { data: taSignals } = useLatestSignals(symbol)

  // Prefer agent signal over TA strategies
  if (agentSignal) {
    const isBuy = agentSignal.type === "buy_signal"
    const isSell = agentSignal.type === "sell_signal"
    if (isBuy || isSell) {
      const Icon = isBuy ? TrendingUp : TrendingDown
      const label = isBuy ? "AI 买入" : "AI 卖出"
      const variant = isBuy ? "default" : "destructive"
      return (
        <Badge variant={variant} className="gap-1 text-[10px]">
          <Icon className="h-3 w-3" />
          {label}
        </Badge>
      )
    }
    // hold_update — show as neutral
    return (
      <Badge variant="secondary" className="gap-1 text-[10px]">
        <Bot className="h-3 w-3" />
        AI 持有
      </Badge>
    )
  }

  // Fallback to TA signals if no agent signal
  if (!taSignals || taSignals.length === 0) return null

  const buySignals = taSignals.filter((s) => s.signal === "buy")
  const sellSignals = taSignals.filter((s) => s.signal === "sell")

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
