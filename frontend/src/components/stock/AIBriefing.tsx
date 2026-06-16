import { useState } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { ChevronDown, ChevronUp, Sparkles } from "lucide-react"
import { useMarketAIOverview } from "@/hooks/useAI"
import { AI_SIGNAL_LABELS } from "@/lib/constants"

export function AIBriefing() {
  const { data, isLoading, error } = useMarketAIOverview()
  const [expanded, setExpanded] = useState(true)

  if (error) return null

  return (
    <Card className="border-l-2 border-l-[var(--accent-primary)] overflow-hidden">
      <CardContent className="p-4">
        <button
          className="flex items-center justify-between w-full text-left"
          onClick={() => setExpanded(!expanded)}
        >
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-accent-primary" />
            <span className="text-title">AI 市场研判</span>
            {data && (
              <Badge variant="outline" className="text-xs border-border text-muted-foreground">
                {AI_SIGNAL_LABELS[data.market_trend] || data.market_trend}
              </Badge>
            )}
          </div>
          {expanded ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
        </button>

        {expanded && (
          <div className="mt-3 space-y-2.5">
            {isLoading ? (
              <div className="flex items-center gap-2 py-2">
                <span className="ai-dot" />
                <span className="ai-dot" />
                <span className="ai-dot" />
                <span className="text-xs text-muted-foreground ml-1">AI 正在分析市场...</span>
              </div>
            ) : data ? (
              <>
                <p className="text-sm text-muted-foreground leading-relaxed">
                  {data.summary || "暂无市场概览"}
                </p>
                {data.key_points && data.key_points.length > 0 && (
                  <ul className="text-xs text-muted-foreground space-y-1 border-l-2 border-accent-primary/30 pl-3">
                    {data.key_points.slice(0, 3).map((point, i) => (
                      <li key={i} className="leading-relaxed">{point}</li>
                    ))}
                  </ul>
                )}
              </>
            ) : (
              <p className="text-xs text-muted-foreground">AI 分析尚未生成</p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
