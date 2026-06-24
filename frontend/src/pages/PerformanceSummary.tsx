/** Performance Summary — AI track record display (v36.0). */

import { Loader2, TrendingUp } from "lucide-react"
import { usePerformanceSummary } from "@/hooks/useMessages"
import type { PerformanceResult } from "@/types/message"
import { cn } from "@/lib/utils"

// ─── ResultBar ────────────────────────────────────────────────────────────────

function ResultBar({ result }: { result: PerformanceResult }) {
  const pct = result.return_pct ?? 0
  const isProfitable = pct > 0
  const barWidth = Math.min(Math.abs(pct) * 10, 100) // scale: 10% = full width
  const sign = isProfitable ? "+" : ""

  return (
    <div className="flex items-center gap-3 py-1.5">
      <span className="text-xs text-muted-foreground w-20 shrink-0 truncate" title={result.name}>
        {result.name}
      </span>
      <div className="flex-1 h-5 rounded bg-muted/30 overflow-hidden relative">
        <div
          className={cn(
            "h-full rounded transition-all",
            isProfitable ? "bg-emerald-500/60" : "bg-red-500/60",
          )}
          style={{ width: `${barWidth}%` }}
        />
      </div>
      <span
        className={cn(
          "text-xs font-mono w-14 text-right shrink-0",
          isProfitable ? "text-emerald-500" : "text-red-500",
        )}
      >
        {sign}{pct.toFixed(1)}%
      </span>
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function PerformanceSummary() {
  const { data, isLoading, error } = usePerformanceSummary()

  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        加载中...
      </div>
    )
  }

  if (error) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold">AI 表现</h1>
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
          加载失败: {(error as Error).message}
        </div>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold">AI 表现</h1>
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <TrendingUp className="h-12 w-12 text-muted-foreground/40 mb-4" />
          <p className="text-muted-foreground">暂无数据</p>
          <p className="text-xs text-muted-foreground/60 mt-1">
            AI 开始提供建议后，这里会显示准确率统计
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6 max-w-2xl">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold">AI 表现</h1>
        <p className="text-sm text-muted-foreground mt-1">
          跟踪 AI 投资建议的历史表现
        </p>
      </div>

      {/* Accuracy headline */}
      <div className="rounded-lg border bg-card p-6 text-center space-y-2">
        <p className="text-sm text-muted-foreground">过去 30 天准确率</p>
        <p className="text-4xl font-bold text-foreground">
          {(data.accuracy_pct ?? 0).toFixed(0)}%
        </p>
        <p className="text-sm text-muted-foreground">
          共 {data.total_signals} 条建议，其中 {data.profitable_signals} 条盈利
        </p>
      </div>

      {/* Recent results bar chart */}
      {data.recent_results.length > 0 && (
        <div className="rounded-lg border bg-card p-5 space-y-3">
          <h3 className="text-sm font-semibold text-foreground">近期结果</h3>
          <div className="space-y-0.5">
            {data.recent_results.map((result) => (
              <ResultBar key={result.id} result={result} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
