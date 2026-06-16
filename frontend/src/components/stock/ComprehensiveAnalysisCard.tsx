import { useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Sparkles, AlertTriangle, ChevronDown, ChevronUp, RefreshCw, AlertCircle } from "lucide-react"
import { useComprehensiveAnalysis } from "@/hooks/useFundFlow"
import { AI_SIGNAL_LABELS } from "@/lib/constants"

interface ComprehensiveAnalysisCardProps {
  symbol: string
}

export function ComprehensiveAnalysisCard({ symbol }: ComprehensiveAnalysisCardProps) {
  const { data, isLoading, error } = useComprehensiveAnalysis(symbol)
  const [expanded, setExpanded] = useState(false)

  if (isLoading) {
    return (
      <Card className="border-l-2 border-l-[var(--accent-primary)]">
        <CardContent className="px-4 py-3">
          <div className="flex items-center gap-2">
            <RefreshCw className="h-4 w-4 text-accent-primary animate-spin" />
            <span className="text-sm text-muted-foreground">AI 速览加载中...</span>
          </div>
        </CardContent>
      </Card>
    )
  }

  if (error) {
    return (
      <Card className="border-destructive/30">
        <CardContent className="px-4 py-3">
          <div className="flex items-center gap-2">
            <AlertCircle className="h-4 w-4 text-destructive shrink-0" />
            <span className="text-sm text-muted-foreground">AI 速览加载失败</span>
          </div>
        </CardContent>
      </Card>
    )
  }

  if (!data || !data.summary) return null

  const signalColor = data.signal === "bullish" ? "var(--color-market-up)" : data.signal === "bearish" ? "var(--color-market-down)" : "var(--color-market-flat)"
  const signalLabel = AI_SIGNAL_LABELS[data.signal] || data.signal
  const pct = Math.round(data.confidence * 100)
  const hasDetails = (data.points && data.points.length > 0) || (data.risks && data.risks.length > 0)

  return (
    <Card className="border-l-2 border-l-[var(--accent-primary)]">
      <CardContent className="px-4 py-3 space-y-2">
        {/* Header row: title + signal badge + confidence + timestamp */}
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Sparkles className="h-3.5 w-3.5 text-accent-primary shrink-0" />
            <span className="text-sm font-medium">AI 速览</span>
            {data.signal && (
              <Badge variant="outline" className="text-[10px]" style={{ color: signalColor, borderColor: signalColor }}>
                {signalLabel}
              </Badge>
            )}
            {data.confidence > 0 && (
              <div className="flex items-center gap-1.5">
                <div className="h-1.5 w-14 rounded-full bg-muted overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{ width: `${pct}%`, backgroundColor: signalColor }}
                  />
                </div>
                <span className="text-[10px] font-numeric text-muted-foreground">{pct}%</span>
              </div>
            )}
          </div>
          {data.generated_at && (
            <span className="text-[10px] text-muted-foreground/50 shrink-0">
              {new Date(data.generated_at).toLocaleString("zh-CN")}
            </span>
          )}
        </div>

        {/* Summary */}
        <p className="text-xs text-foreground leading-relaxed">{data.summary}</p>

        {/* Expandable details: points + risks */}
        {hasDetails && (
          <>
            {expanded && (
              <div className="space-y-2 pt-1">
                {data.points && data.points.length > 0 && (
                  <ul className="space-y-1">
                    {data.points.map((point, i) => (
                      <li key={i} className="text-[11px] text-muted-foreground flex items-start gap-1.5">
                        <span className="text-accent-primary mt-0.5 shrink-0">&#x2022;</span>
                        <span>{point}</span>
                      </li>
                    ))}
                  </ul>
                )}
                {data.risks && data.risks.length > 0 && (
                  <div className="pt-1 border-t border-dashed space-y-1">
                    {data.risks.map((risk, i) => (
                      <div key={i} className="text-[10px] text-warning flex items-start gap-1">
                        <AlertTriangle className="h-3 w-3 shrink-0 mt-0.5" />
                        <span>{risk}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
            <button
              onClick={() => setExpanded(!expanded)}
              className="flex items-center gap-1 text-[11px] text-accent-primary hover:text-accent-primary transition-colors"
            >
              {expanded ? (
                <>收起 <ChevronUp className="h-3 w-3" /></>
              ) : (
                <>展开详情 <ChevronDown className="h-3 w-3" /></>
              )}
            </button>
          </>
        )}
      </CardContent>
    </Card>
  )
}
