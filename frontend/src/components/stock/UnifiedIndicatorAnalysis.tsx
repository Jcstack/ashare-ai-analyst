import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { BarChart3, ChevronDown, Info } from "lucide-react"
import { cn } from "@/lib/utils"
import { useBayesianIndicators } from "@/hooks/useAnalysis"
import { GlossaryTooltip } from "@/components/ui/glossary-tooltip"
import type { IndicatorsSummary } from "@/types/stock"

/** Map indicator display names (Chinese) to glossary keys */
const INDICATOR_GLOSSARY_KEY: Record<string, string> = {
  MACD: "MACD",
  RSI: "RSI",
  KDJ: "KDJ",
  "布林带": "BOLL",
  BOLL: "BOLL",
  "Bollinger": "BOLL",
  OBV: "OBV",
  VWAP: "VWAP",
  ATR: "ATR",
  MA: "MA",
  EMA: "EMA",
  "换手率": "turnover_rate",
  "成交量": "volume",
}

function getGlossaryKey(indicatorName: string): string | null {
  // Direct match
  if (INDICATOR_GLOSSARY_KEY[indicatorName]) return INDICATOR_GLOSSARY_KEY[indicatorName]
  // Partial match: check if any key is contained in the name
  for (const [key, glossaryKey] of Object.entries(INDICATOR_GLOSSARY_KEY)) {
    if (indicatorName.includes(key)) return glossaryKey
  }
  return null
}

/** A-share convention: red = up, green = down, gray = flat */
const PROB_COLORS = {
  up: "var(--color-market-up)",
  flat: "var(--color-market-flat)",
  down: "var(--color-market-down)",
} as const

const SIGNAL_STYLES: Record<string, { color: string; bg: string }> = {
  bullish: { color: "var(--color-market-up)", bg: "color-mix(in srgb, var(--color-market-up) 8%, transparent)" },
  bearish: { color: "var(--color-market-down)", bg: "color-mix(in srgb, var(--color-market-down) 8%, transparent)" },
  neutral: { color: "var(--color-market-flat)", bg: "color-mix(in srgb, var(--color-market-flat) 8%, transparent)" },
}

function getSignalStyle(signal: string) {
  if (signal.includes("多") || signal.includes("bullish")) return SIGNAL_STYLES.bullish
  if (signal.includes("空") || signal.includes("bearish")) return SIGNAL_STYLES.bearish
  return SIGNAL_STYLES.neutral
}

interface UnifiedIndicatorAnalysisProps {
  symbol: string
  indicators: IndicatorsSummary | undefined
}

export function UnifiedIndicatorAnalysis({ symbol, indicators }: UnifiedIndicatorAnalysisProps) {
  const { data: bayesian, isLoading } = useBayesianIndicators(symbol)
  const [methodOpen, setMethodOpen] = useState(false)

  if (isLoading) {
    return (
      <Card>
        <CardHeader className="py-3">
          <Skeleton className="h-5 w-48" />
        </CardHeader>
        <CardContent className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-14 w-full rounded-lg" />
          ))}
        </CardContent>
      </Card>
    )
  }

  if (!bayesian) {
    // Fallback: show just the raw indicator values if bayesian data unavailable
    if (!indicators?.values) return null
    return (
      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <BarChart3 className="h-4 w-4 text-accent-primary" />
            技术指标概览
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {Object.entries(indicators.values).map(([key, val]) => {
              const gKey = getGlossaryKey(key)
              return (
                <div key={key} className="rounded-lg border p-2.5">
                  <span className="text-xs text-muted-foreground">
                    {gKey ? <GlossaryTooltip term={gKey}>{key}</GlossaryTooltip> : key}
                  </span>
                  <p className="text-sm font-mono tabular-nums mt-0.5">
                    {val != null ? Number(val).toFixed(2) : "—"}
                  </p>
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>
    )
  }

  const { composite, indicators: bayesianItems } = bayesian
  const signalStyle = getSignalStyle(composite.signal)

  return (
    <Card>
      <CardHeader className="py-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-2">
            <BarChart3 className="h-4 w-4 text-accent-primary" />
            综合指标分析
          </CardTitle>
          <span className="text-[10px] text-muted-foreground">
            回看{bayesian.lookback_days}日 · 预测{bayesian.forward_days}日
          </span>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Per-indicator rows */}
        <div className="space-y-2">
          {bayesianItems.map((item) => {
            const dominant =
              item.probabilities.up >= item.probabilities.down && item.probabilities.up >= item.probabilities.flat
                ? "up" as const
                : item.probabilities.down >= item.probabilities.up && item.probabilities.down >= item.probabilities.flat
                  ? "down" as const
                  : "flat" as const

            return (
              <div
                key={item.indicator}
                className="grid grid-cols-[140px_1fr_1fr] md:grid-cols-[160px_200px_1fr] items-center gap-3 rounded-lg border p-3"
              >
                {/* Left: indicator name + value */}
                <div className="min-w-0">
                  <span className="text-sm font-medium block truncate">
                    {(() => {
                      const gKey = getGlossaryKey(item.indicator)
                      return gKey
                        ? <GlossaryTooltip term={gKey}>{item.indicator}</GlossaryTooltip>
                        : item.indicator
                    })()}
                  </span>
                  <span className="text-xs font-mono tabular-nums text-muted-foreground">
                    {item.current_value.toFixed(2)}
                  </span>
                </div>

                {/* Middle: mini probability bar */}
                <div className="space-y-1">
                  <div className="flex h-4 w-full rounded-full overflow-hidden">
                    {item.probabilities.up > 0 && (
                      <div
                        className="h-full flex items-center justify-center text-[9px] font-medium text-white"
                        style={{
                          width: `${Math.max(item.probabilities.up * 100, 3)}%`,
                          backgroundColor: PROB_COLORS.up,
                        }}
                      >
                        {item.probabilities.up >= 0.15 && `${(item.probabilities.up * 100).toFixed(0)}%`}
                      </div>
                    )}
                    {item.probabilities.flat > 0 && (
                      <div
                        className="h-full flex items-center justify-center text-[9px] font-medium text-white"
                        style={{
                          width: `${Math.max(item.probabilities.flat * 100, 3)}%`,
                          backgroundColor: PROB_COLORS.flat,
                        }}
                      >
                        {item.probabilities.flat >= 0.15 && `${(item.probabilities.flat * 100).toFixed(0)}%`}
                      </div>
                    )}
                    {item.probabilities.down > 0 && (
                      <div
                        className="h-full flex items-center justify-center text-[9px] font-medium text-white"
                        style={{
                          width: `${Math.max(item.probabilities.down * 100, 3)}%`,
                          backgroundColor: PROB_COLORS.down,
                        }}
                      >
                        {item.probabilities.down >= 0.15 && `${(item.probabilities.down * 100).toFixed(0)}%`}
                      </div>
                    )}
                  </div>
                  {!item.data_sufficient && (
                    <span className="text-[10px] text-warning">样本不足</span>
                  )}
                </div>

                {/* Right: one-line interpretation */}
                <p className="text-xs leading-relaxed" style={{ color: PROB_COLORS[dominant] }}>
                  {item.interpretation}
                </p>
              </div>
            )
          })}
        </div>

        {/* Composite signal summary */}
        <div className="rounded-lg p-3 space-y-2" style={{ backgroundColor: signalStyle.bg }}>
          <div className="flex items-center gap-3 flex-wrap">
            <Badge
              className="text-sm px-3 py-1"
              style={{ backgroundColor: signalStyle.color, color: "white" }}
            >
              {composite.signal}
            </Badge>
            <div className="flex items-center gap-3 text-xs text-muted-foreground">
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
          <p className="text-sm text-muted-foreground leading-relaxed">{composite.summary}</p>
        </div>

        {/* Methodology collapsible */}
        <Collapsible open={methodOpen} onOpenChange={setMethodOpen}>
          <CollapsibleTrigger className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors">
            <Info className="h-3.5 w-3.5" />
            贝叶斯分析方法说明
            <ChevronDown className={cn("h-3 w-3 transition-transform", methodOpen && "rotate-180")} />
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="mt-2 rounded-lg border bg-muted/30 p-3 text-xs text-muted-foreground leading-relaxed space-y-1">
              <p>贝叶斯概率分析基于历史数据统计，计算当指标处于某一区间时，未来 N 日股价上涨/下跌/持平的条件概率。</p>
              <p>综合信号由多个指标的概率加权得出，非单一指标决策。历史概率不代表未来表现，仅供参考。</p>
            </div>
          </CollapsibleContent>
        </Collapsible>
      </CardContent>
    </Card>
  )
}
