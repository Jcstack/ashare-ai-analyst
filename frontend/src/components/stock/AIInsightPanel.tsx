import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Sparkles, RefreshCw, AlertTriangle, Target, TrendingUp, TrendingDown, Minus } from "lucide-react"
import { useAIAnalysis, useTriggerAnalysis } from "@/hooks/useAI"
import { formatPrice, cn } from "@/lib/utils"
import { formatTime } from "@/lib/formatters"
import { AI_SIGNAL_LABELS, SIGNAL_LABELS, RISK_LABELS, MARKET_COLORS } from "@/lib/constants"
import { AIAnalysisCard } from "@/components/ai/AIAnalysisCard"

interface AIInsightPanelProps {
  symbol: string
}

export function AIInsightPanel({ symbol }: AIInsightPanelProps) {
  const { data, isLoading, error } = useAIAnalysis(symbol)
  const trigger = useTriggerAnalysis(symbol)

  const isEmpty = !data || data.status === "error"

  return (
    <AIAnalysisCard
      title="AI 深度分析"
      icon={<Sparkles className="h-5 w-5 text-accent-primary" />}
      isLoading={isLoading}
      error={error}
      isEmpty={isEmpty}
      emptyMessage={data?.message || "点击按钮生成AI分析报告"}
      onGenerate={() => trigger.mutate()}
      onRetry={() => trigger.mutate()}
      isRetrying={trigger.isPending}
      generatedAt={data?.generated_at}
    >
      <AIInsightContent data={data!} trigger={trigger} />
    </AIAnalysisCard>
  )
}

function AIInsightContent({
  data,
  trigger,
}: {
  data: NonNullable<ReturnType<typeof useAIAnalysis>["data"]>
  trigger: ReturnType<typeof useTriggerAnalysis>
}) {
  const TrendIcon = data.trend === "bullish" ? TrendingUp : data.trend === "bearish" ? TrendingDown : Minus
  const trendColor = data.trend === "bullish" ? MARKET_COLORS.up : data.trend === "bearish" ? MARKET_COLORS.down : MARKET_COLORS.flat

  return (
    <>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-accent-primary" />
          <span className="text-title">AI 深度分析</span>
          {data.generated_at && (
            <span className="text-micro text-muted-foreground">{formatTime(data.generated_at)}</span>
          )}
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => trigger.mutate()}
          disabled={trigger.isPending}
        >
          <RefreshCw className={cn("h-4 w-4", trigger.isPending && "animate-spin")} />
        </Button>
      </div>

      {/* Signal + Confidence */}
      <div className="flex items-center gap-3 flex-wrap">
        <Badge className="gap-1 text-sm px-3 py-1" style={{ backgroundColor: trendColor, color: "white" }}>
          <TrendIcon className="h-4 w-4" />
          {AI_SIGNAL_LABELS[data.trend] || data.trend}
        </Badge>
        {data.signal && (
          <Badge variant="outline" className="px-2.5">{SIGNAL_LABELS[data.signal] || data.signal}</Badge>
        )}
        {data.confidence != null && (
          <div className="flex items-center gap-2">
            <div className="h-1.5 w-20 rounded-full bg-muted overflow-hidden">
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: `${Math.round(data.confidence * 100)}%`,
                  backgroundColor: trendColor,
                }}
              />
            </div>
            <span className="price-sm">{Math.round(data.confidence * 100)}%</span>
          </div>
        )}
        {data.risk_level && (
          <Badge variant="outline" className="text-xs">
            {RISK_LABELS[data.risk_level] || data.risk_level}
          </Badge>
        )}
      </div>

      <div className="border-t border-white/[0.06]" />

      {/* Reasoning */}
      {data.reasoning && data.reasoning.length > 0 && (
        <div className="space-y-2">
          <p className="text-caption font-semibold text-muted-foreground">分析要点</p>
          <div className="space-y-2">
            {data.reasoning.map((point: string, i: number) => (
              <div key={i} className="flex items-start gap-2.5">
                <span className="shrink-0 w-5 h-5 rounded-full bg-accent-primary/20 text-accent-primary text-xs flex items-center justify-center font-medium mt-0.5">
                  {i + 1}
                </span>
                <span className="text-sm leading-relaxed">{point}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Target Price */}
      {data.target_price_range && (
        <>
          <div className="border-t border-white/[0.06]" />
          <div className="flex items-center gap-2 text-sm">
            <Target className="h-4 w-4 text-muted-foreground" />
            <span className="text-muted-foreground">目标价:</span>
            <span className="price-md font-semibold">
              {formatPrice(data.target_price_range.low)} — {formatPrice(data.target_price_range.high)}
            </span>
          </div>
        </>
      )}

      {/* Key Factors */}
      {data.key_factors && data.key_factors.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {data.key_factors.map((f: string, i: number) => (
            <Badge key={i} variant="secondary" className="text-xs">{f}</Badge>
          ))}
        </div>
      )}

      {/* Risk Warnings */}
      {data.risk_warnings && data.risk_warnings.length > 0 && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 space-y-1.5">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-destructive">
            <AlertTriangle className="h-3.5 w-3.5" />
            风险提示
          </div>
          <ul className="text-xs text-destructive/80 space-y-1 ml-5 list-disc">
            {data.risk_warnings.map((w: string, i: number) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="text-micro text-muted-foreground/50 text-right">
        Powered by Claude
      </div>
    </>
  )
}
