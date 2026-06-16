import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { BarChart3, AlertCircle } from "lucide-react"
import { useBayesianIndicators } from "@/hooks/useAnalysis"
import { IndicatorProbabilityBar } from "./IndicatorProbabilityBar"

/** Composite signal color mapping (A-share convention) */
const COMPOSITE_SIGNAL_STYLES: Record<string, { color: string; bg: string; label: string }> = {
  "\u504F\u591A": { color: "var(--color-market-up)", bg: "color-mix(in srgb, var(--color-market-up) 10%, transparent)", label: "\u504F\u591A" }, // 偏多
  "\u504F\u7A7A": { color: "var(--color-market-down)", bg: "color-mix(in srgb, var(--color-market-down) 10%, transparent)", label: "\u504F\u7A7A" }, // 偏空
  "\u4E2D\u6027": { color: "var(--color-market-flat)", bg: "color-mix(in srgb, var(--color-market-flat) 10%, transparent)", label: "\u4E2D\u6027" }, // 中性
}

function getSignalStyle(signal: string) {
  // Match by checking if the signal contains known keywords
  if (signal.includes("\u591A") || signal.includes("bullish")) {
    return COMPOSITE_SIGNAL_STYLES["\u504F\u591A"]
  }
  if (signal.includes("\u7A7A") || signal.includes("bearish")) {
    return COMPOSITE_SIGNAL_STYLES["\u504F\u7A7A"]
  }
  return COMPOSITE_SIGNAL_STYLES["\u4E2D\u6027"]
}

function LoadingSkeleton() {
  return (
    <Card>
      <CardHeader className="py-3">
        <div className="flex items-center gap-2">
          <Skeleton className="h-5 w-5 rounded" />
          <Skeleton className="h-4 w-40" />
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <Skeleton className="h-6 w-32" />
        <Skeleton className="h-4 w-full" />
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="space-y-2 rounded-lg border p-3">
            <Skeleton className="h-4 w-48" />
            <Skeleton className="h-5 w-full rounded-full" />
            <Skeleton className="h-3 w-64" />
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

interface BayesianInsightCardProps {
  symbol: string
}

export function BayesianInsightCard({ symbol }: BayesianInsightCardProps) {
  const { data, isLoading, error } = useBayesianIndicators(symbol)

  if (isLoading) return <LoadingSkeleton />

  if (error || !data) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12 text-muted-foreground gap-3">
          <AlertCircle className="h-10 w-10 opacity-40" />
          <p className="text-sm">
            {error ? "贝叶斯指标分析加载失败" : "暂无数据"}
          </p>
        </CardContent>
      </Card>
    )
  }

  const { composite, indicators, analysis_date, lookback_days, forward_days } = data
  const signalStyle = getSignalStyle(composite.signal)

  return (
    <Card>
      <CardHeader className="py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <BarChart3 className="h-5 w-5 text-accent-primary" />
            <CardTitle className="text-sm">贝叶斯概率分析</CardTitle>
          </div>
          <span className="text-[10px] text-muted-foreground">
            {analysis_date} | 回看{lookback_days}日 | 预测{forward_days}日
          </span>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Composite signal header */}
        <div className="rounded-lg p-3 space-y-2" style={{ backgroundColor: signalStyle.bg }}>
          <div className="flex items-center gap-3 flex-wrap">
            <Badge
              className="text-sm px-3 py-1"
              style={{ backgroundColor: signalStyle.color, color: "white" }}
            >
              {composite.signal}
            </Badge>
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className="flex items-center gap-1">
                <span className="inline-block w-2 h-2 rounded-full bg-market-up" />
                偏多 {composite.bullish_count}
              </span>
              <span className="flex items-center gap-1">
                <span className="inline-block w-2 h-2 rounded-full bg-market-flat" />
                中性 {composite.neutral_count}
              </span>
              <span className="flex items-center gap-1">
                <span className="inline-block w-2 h-2 rounded-full bg-market-down" />
                偏空 {composite.bearish_count}
              </span>
            </div>
          </div>
          <p className="text-sm text-muted-foreground leading-relaxed">
            {composite.summary}
          </p>
        </div>

        {/* Individual indicator probability bars */}
        <div className="space-y-2">
          {indicators.map((item) => (
            <IndicatorProbabilityBar key={item.indicator} item={item} />
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
