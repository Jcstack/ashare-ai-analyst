import { useMacroFlowOverview } from "@/hooks/useCapitalFlow"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  ArrowUpRight,
  ArrowDownRight,
  Minus,
  Thermometer,
  Loader2,
} from "lucide-react"
import type { MacroChannelItem } from "@/types/capital-flow"

const CHANNEL_LABELS: Record<string, string> = {
  northbound: "北向",
  southbound: "南向",
  margin: "融资",
  etf: "ETF",
}

function DirectionIcon({ direction }: { direction: string }) {
  if (direction === "up")
    return <ArrowUpRight className="h-3 w-3 text-market-up" />
  if (direction === "down")
    return <ArrowDownRight className="h-3 w-3 text-market-down" />
  return <Minus className="h-3 w-3 text-muted-foreground" />
}

function ChannelChip({ item }: { item: MacroChannelItem }) {
  const label = CHANNEL_LABELS[item.channel] ?? item.channel
  const valueStr =
    item.value >= 0
      ? `+${item.value.toFixed(1)}`
      : item.value.toFixed(1)
  const colorClass =
    item.direction === "up"
      ? "text-market-up"
      : item.direction === "down"
        ? "text-market-down"
        : "text-muted-foreground"

  return (
    <div className="flex items-center gap-1 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <DirectionIcon direction={item.direction} />
      <span className={`font-mono tabular-nums ${colorClass}`}>
        {valueStr}亿
      </span>
    </div>
  )
}

function ScoreBar({ score }: { score: number }) {
  // Map score [-100, +100] to percentage [0%, 100%]
  const pct = Math.max(0, Math.min(100, (score + 100) / 2))

  return (
    <div className="relative h-2 w-full rounded-full bg-muted overflow-hidden">
      {/* Gradient background */}
      <div
        className="absolute inset-0 rounded-full"
        style={{
          background:
            "linear-gradient(to right, var(--color-market-down), var(--color-muted), var(--color-market-up))",
          opacity: 0.3,
        }}
      />
      {/* Pointer */}
      <div
        className="absolute top-0 h-full w-1 rounded-full bg-foreground transition-all duration-500"
        style={{ left: `calc(${pct}% - 2px)` }}
      />
    </div>
  )
}

export function CapitalFlowGauge() {
  const { data, isLoading, isError } = useMacroFlowOverview()

  if (isLoading) {
    return (
      <Card>
        <CardContent className="py-3 px-4 flex items-center gap-2 text-muted-foreground text-xs">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          加载资金面数据...
        </CardContent>
      </Card>
    )
  }

  if (isError || !data) return null

  const scoreLabel =
    data.environment_score >= 0
      ? `+${data.environment_score.toFixed(0)}`
      : data.environment_score.toFixed(0)

  const signalVariant =
    data.signal === "bullish"
      ? "default"
      : data.signal === "bearish"
        ? "destructive"
        : ("secondary" as const)

  const signalText =
    data.signal === "bullish"
      ? "偏多"
      : data.signal === "bearish"
        ? "偏空"
        : "中性"

  return (
    <Card>
      <CardContent className="py-3 px-4 space-y-2">
        {/* Header row */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Thermometer className="h-3.5 w-3.5" />
            <span>资金温度计</span>
            {data.date && (
              <span className="text-[10px] opacity-60">{data.date}</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={signalVariant} className="text-[10px] h-5 px-1.5">
              {signalText}
            </Badge>
            <span className="font-mono tabular-nums text-sm font-semibold">
              {scoreLabel}
            </span>
          </div>
        </div>

        {/* Score bar */}
        <ScoreBar score={data.environment_score} />

        {/* Interpretation */}
        {data.interpretation && (
          <p className="text-xs text-muted-foreground leading-relaxed">
            {data.interpretation}
          </p>
        )}

        {/* Channel breakdown */}
        <div className="flex items-center justify-between gap-2 flex-wrap">
          {data.channels.map((ch) => (
            <ChannelChip key={ch.channel} item={ch} />
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
