import { useState } from "react"
import { Link } from "react-router-dom"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { BrainCircuit, ChevronDown, ArrowRight } from "lucide-react"
import { useMarketAIOverview } from "@/hooks/useAI"
import { useMarketIndices } from "@/hooks/useMarket"
import { AI_SIGNAL_LABELS, MARKET_COLORS } from "@/lib/constants"
import { formatPercent, formatPrice } from "@/lib/utils"

export function AgentBriefingCard() {
  const { data: aiData, isLoading: aiLoading } = useMarketAIOverview()
  const { data: indices = [] } = useMarketIndices()
  const [detailOpen, setDetailOpen] = useState(false)

  const trendLabel = aiData ? AI_SIGNAL_LABELS[aiData.market_trend] || aiData.market_trend : null

  return (
    <Card className="agent-surface">
      <CardContent className="py-5 pl-5 pr-4 space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <BrainCircuit className="h-4 w-4" style={{ color: "var(--color-agent)" }} />
            <span className="text-title">Agent 市场简报</span>
            {trendLabel && (
              <Badge
                variant="outline"
                className="text-xs"
                style={{ borderColor: "var(--color-agent-border)", color: "var(--color-agent)" }}
              >
                {trendLabel}
              </Badge>
            )}
          </div>
          <Link
            to="/market"
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            市场全景 <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>

        {/* AI Summary */}
        {aiLoading ? (
          <div className="space-y-2">
            <div className="flex items-center gap-2.5">
              <span className="ai-dot" />
              <span className="ai-dot" />
              <span className="ai-dot" />
              <span className="text-xs text-muted-foreground ml-1">Agent 正在分析市场...</span>
            </div>
            <Skeleton className="h-12 w-full rounded-lg" />
          </div>
        ) : aiData ? (
          <p className="text-body text-muted-foreground whitespace-pre-line">
            {aiData.summary || "暂无市场概览"}
          </p>
        ) : (
          <p className="text-sm text-muted-foreground">市场分析尚未生成</p>
        )}

        {/* Compact index strip */}
        {indices.length > 0 && (
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs">
            {indices.slice(0, 4).map((idx) => {
              const color = idx.pct_change > 0 ? MARKET_COLORS.up : idx.pct_change < 0 ? MARKET_COLORS.down : MARKET_COLORS.flat
              return (
                <span key={idx.name} className="flex items-center gap-1.5">
                  <span className="text-muted-foreground">{idx.name}</span>
                  <span className="font-numeric font-medium" style={{ color }}>
                    {formatPrice(idx.price)}
                  </span>
                  <span className="font-numeric" style={{ color }}>
                    {formatPercent(idx.pct_change)}
                  </span>
                </span>
              )
            })}
          </div>
        )}

        {/* Expandable detail: AI key points */}
        {aiData && aiData.key_points && aiData.key_points.length > 0 && (
          <>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground gap-1"
              onClick={() => setDetailOpen(!detailOpen)}
            >
              {detailOpen ? "收起详情" : "展开详情"}
              <ChevronDown className={`h-3.5 w-3.5 transition-transform ${detailOpen ? "rotate-180" : ""}`} />
            </Button>
            {detailOpen && (
              <ul className="text-xs text-muted-foreground space-y-1.5 border-l-2 pl-3 content-reveal" style={{ borderColor: "var(--color-agent-border)" }}>
                {aiData.key_points.map((point, i) => (
                  <li key={i} className="leading-relaxed">{point}</li>
                ))}
              </ul>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
