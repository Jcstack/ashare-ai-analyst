import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Sparkles, AlertTriangle, CheckCircle2, AlertCircle } from "lucide-react"
import { useDragonTigerAI } from "@/hooks/useAnalysis"
import { cn } from "@/lib/utils"
import { formatTime } from "@/lib/formatters"

/** Signal badge color mapping (A-share convention) */
const SIGNAL_STYLES: Record<string, { color: string; label: string }> = {
  bullish: { color: "var(--color-market-up)", label: "看涨" },
  bearish: { color: "var(--color-market-down)", label: "看跌" },
  neutral: { color: "var(--color-market-flat)", label: "中性" },
}

function getSignalStyle(signal: string) {
  if (signal.includes("bullish") || signal.includes("看涨") || signal.includes("偏多")) {
    return SIGNAL_STYLES.bullish
  }
  if (signal.includes("bearish") || signal.includes("看跌") || signal.includes("偏空")) {
    return SIGNAL_STYLES.bearish
  }
  return SIGNAL_STYLES.neutral
}

function LoadingSkeleton() {
  return (
    <Card className="border-l-2 border-l-[var(--accent-primary)]">
      <CardContent className="p-4 space-y-4">
        <div className="flex items-center gap-2">
          <Skeleton className="h-5 w-5 rounded" />
          <Skeleton className="h-4 w-44" />
        </div>
        <Skeleton className="h-6 w-28" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-3/4" />
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-3 w-full" />
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

interface DragonTigerAICardProps {
  symbol: string
}

export function DragonTigerAICard({ symbol }: DragonTigerAICardProps) {
  const { data, isLoading, error } = useDragonTigerAI(symbol)

  if (isLoading) return <LoadingSkeleton />

  if (error || !data) {
    return (
      <Card className="border-l-2 border-l-[var(--accent-primary)]">
        <CardContent className="flex flex-col items-center justify-center py-10 text-muted-foreground gap-3">
          <AlertCircle className="h-8 w-8 opacity-40" />
          <p className="text-sm">龙虎榜 AI 分析暂不可用</p>
        </CardContent>
      </Card>
    )
  }

  // Handle non-success status (e.g., "no_data")
  if (data.status !== "success" && data.status !== "ok") {
    return (
      <Card className="border-l-2 border-l-[var(--accent-primary)]">
        <CardContent className="p-4">
          <div className="flex items-center gap-2 mb-2">
            <Sparkles className="h-5 w-5 text-accent-primary" />
            <span className="text-title">龙虎榜 AI 解读</span>
          </div>
          <p className="text-sm text-muted-foreground">
            {data.message || "暂无龙虎榜 AI 分析数据"}
          </p>
        </CardContent>
      </Card>
    )
  }

  const signalStyle = getSignalStyle(data.signal)

  return (
    <Card className="border-l-2 border-l-[var(--accent-primary)]">
      <CardContent className="p-4 space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-accent-primary" />
            <span className="text-title">龙虎榜 AI 解读</span>
          </div>
          {data.generated_at && (
            <span className="text-micro text-muted-foreground">{formatTime(data.generated_at)}</span>
          )}
        </div>

        {/* Signal + Confidence */}
        <div className="flex items-center gap-3 flex-wrap">
          <Badge
            className="gap-1 text-sm px-3 py-1"
            style={{ backgroundColor: signalStyle.color, color: "white" }}
          >
            {signalStyle.label}
          </Badge>
          {data.confidence != null && (
            <div className="flex items-center gap-2">
              <div className="h-1.5 w-20 rounded-full bg-muted overflow-hidden">
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${Math.round(data.confidence * 100)}%`,
                    backgroundColor: signalStyle.color,
                  }}
                />
              </div>
              <span className="price-sm">{Math.round(data.confidence * 100)}%</span>
            </div>
          )}
        </div>

        {/* Summary */}
        <p className="text-sm leading-relaxed">{data.summary}</p>

        <div className="border-t border-white/[0.06]" />

        {/* Key Findings */}
        {data.key_findings && data.key_findings.length > 0 && (
          <div className="space-y-2">
            <p className="text-caption font-semibold text-muted-foreground">核心发现</p>
            <div className="space-y-1.5">
              {data.key_findings.map((finding, i) => (
                <div key={i} className="flex items-start gap-2">
                  <CheckCircle2 className="h-4 w-4 text-accent-primary shrink-0 mt-0.5" />
                  <span className="text-sm leading-relaxed">{finding}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Risk Factors */}
        {data.risk_factors && data.risk_factors.length > 0 && (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 space-y-1.5">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-destructive">
              <AlertTriangle className="h-3.5 w-3.5" />
              风险因素
            </div>
            <ul className="text-xs text-destructive/80 space-y-1 ml-5 list-disc">
              {data.risk_factors.map((factor, i) => (
                <li key={i}>{factor}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Reasoning chain */}
        {data.reasoning && data.reasoning.length > 0 && (
          <div className="space-y-2">
            <p className="text-caption font-semibold text-muted-foreground">推理链</p>
            <div className="space-y-2">
              {data.reasoning.map((step, i) => (
                <div key={i} className="flex items-start gap-2.5">
                  <span className="shrink-0 w-5 h-5 rounded-full bg-accent-primary/20 text-accent-primary text-xs flex items-center justify-center font-medium mt-0.5">
                    {i + 1}
                  </span>
                  <span className="text-sm leading-relaxed">{step}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Historical performance stats */}
        {data.historical_performance && (
          <>
            <div className="border-t border-white/[0.06]" />
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="text-center">
                <p className="text-[10px] text-muted-foreground">近3月上榜</p>
                <p className="text-sm font-semibold font-numeric">
                  {data.historical_performance.appearances_3m} 次
                </p>
              </div>
              <div className="text-center">
                <p className="text-[10px] text-muted-foreground">机构净买入</p>
                <p className={cn(
                  "text-sm font-semibold font-numeric",
                  data.historical_performance.institution_net_buy >= 0 ? "text-market-up" : "text-market-down",
                )}>
                  {data.historical_performance.institution_net_buy >= 0 ? "+" : ""}
                  {(data.historical_performance.institution_net_buy / 1e4).toFixed(2)}万
                </p>
              </div>
              <div className="text-center">
                <p className="text-[10px] text-muted-foreground">5日平均收益</p>
                <p className={cn(
                  "text-sm font-semibold font-numeric",
                  data.historical_performance.avg_return_5d >= 0 ? "text-market-up" : "text-market-down",
                )}>
                  {data.historical_performance.avg_return_5d >= 0 ? "+" : ""}
                  {data.historical_performance.avg_return_5d.toFixed(2)}%
                </p>
              </div>
              <div className="text-center">
                <p className="text-[10px] text-muted-foreground">5日胜率</p>
                <p className="text-sm font-semibold font-numeric">
                  {(data.historical_performance.win_rate_5d * 100).toFixed(0)}%
                </p>
              </div>
            </div>
          </>
        )}

        {/* Attribution */}
        <div className="text-micro text-muted-foreground/50 text-right">
          Powered by Claude
        </div>
      </CardContent>
    </Card>
  )
}
