import { useState } from "react"
import { ChevronDown, ChevronUp, RefreshCw, TrendingDown, TrendingUp } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { FactorBar } from "@/components/analysis/FactorBar"
import { MARKET_COLORS } from "@/lib/constants"
import { formatPrice } from "@/lib/utils"
import type { MoveAnalysis } from "@/types/agent"

interface Props {
  data: MoveAnalysis | null
  isLoading: boolean
  error: Error | null
  onRefresh?: () => void
}

export function MoveAnalysisPanel({ data, isLoading, error, onRefresh }: Props) {
  const [showReasoning, setShowReasoning] = useState(false)

  if (isLoading) {
    return (
      <div className="space-y-3 p-4">
        <Skeleton className="h-5 w-3/4" />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-20 w-full" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-4 text-center text-sm text-muted-foreground">
        分析失败: {error.message}
        {onRefresh && (
          <Button variant="ghost" size="sm" className="ml-2" onClick={onRefresh}>
            <RefreshCw className="h-3.5 w-3.5 mr-1" /> 重试
          </Button>
        )}
      </div>
    )
  }

  if (!data || data.status === "error") {
    return (
      <div className="p-4 text-center text-sm text-muted-foreground">
        {data?.message ?? "暂无分析数据"}
        {onRefresh && (
          <Button variant="ghost" size="sm" className="ml-2" onClick={onRefresh}>
            <RefreshCw className="h-3.5 w-3.5 mr-1" /> 生成分析
          </Button>
        )}
      </div>
    )
  }

  const isUp = (data.price_change ?? 0) >= 0
  const priceColor = isUp ? MARKET_COLORS.up : MARKET_COLORS.down
  const PriceIcon = isUp ? TrendingUp : TrendingDown

  return (
    <div className="space-y-4 p-4">
      {/* Summary */}
      <div className="flex items-start gap-2">
        <PriceIcon className="h-4 w-4 mt-0.5 shrink-0" style={{ color: priceColor }} />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium">{data.move_summary}</p>
          {data.price_change != null && (
            <span className="text-xs font-numeric" style={{ color: priceColor }}>
              {data.price_change >= 0 ? "+" : ""}{data.price_change.toFixed(2)}%
            </span>
          )}
        </div>
        {onRefresh && (
          <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" onClick={onRefresh}>
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
        )}
      </div>

      {/* Factor attribution bars */}
      {data.factors.length > 0 && (
        <div>
          <h4 className="text-xs font-medium text-muted-foreground mb-2">归因因子</h4>
          <FactorBar factors={data.factors} />
        </div>
      )}

      {/* Position context advice */}
      {data.position_context && (
        <div className="rounded-lg border bg-accent/30 p-3 space-y-1.5">
          <h4 className="text-xs font-medium">持仓建议</h4>
          <p className="text-sm">{data.position_context.advice}</p>
          {data.position_context.key_levels && (
            <div className="flex gap-4 text-xs text-muted-foreground">
              <span>支撑位: <span className="font-numeric text-foreground">{formatPrice(data.position_context.key_levels.support)}</span></span>
              <span>压力位: <span className="font-numeric text-foreground">{formatPrice(data.position_context.key_levels.resistance)}</span></span>
            </div>
          )}
        </div>
      )}

      {/* Outlook */}
      {data.outlook && (
        <div>
          <h4 className="text-xs font-medium text-muted-foreground mb-1">短期展望</h4>
          <p className="text-sm text-muted-foreground">{data.outlook}</p>
        </div>
      )}

      {/* Reasoning chain (collapsible) */}
      {data.reasoning.length > 0 && (
        <div>
          <button
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
            onClick={() => setShowReasoning(!showReasoning)}
          >
            {showReasoning ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            {showReasoning ? "收起推理链" : "展开推理链"}
          </button>
          {showReasoning && (
            <ol className="mt-2 space-y-1 text-xs text-muted-foreground list-decimal list-inside">
              {data.reasoning.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ol>
          )}
        </div>
      )}

      {/* Footer */}
      {data.generated_at && (
        <div className="flex items-center justify-between text-[10px] text-muted-foreground">
          <span>{new Date(data.generated_at).toLocaleString("zh-CN")}</span>
          {data.model_used && <Badge variant="secondary" className="text-[10px]">{data.model_used}</Badge>}
        </div>
      )}
    </div>
  )
}
