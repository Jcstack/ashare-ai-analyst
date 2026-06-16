import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Sparkles, TrendingUp, TrendingDown, Minus, Layers } from "lucide-react"
import { useStockConcepts } from "@/hooks/useConcept"
import { ConceptDetailSheet } from "./ConceptDetailSheet"
import type { StockConceptItem } from "@/types/concept"

interface ConceptTagBarProps {
  symbol: string
}

const RESONANCE_CONFIG: Record<string, { label: string; bg: string; text: string; border: string }> = {
  strong: { label: "强共振", bg: "bg-market-up/10", text: "text-market-up", border: "border-market-up/30" },
  moderate: { label: "概念共振", bg: "bg-warning/10", text: "text-warning", border: "border-warning/30" },
  weak: { label: "弱共振", bg: "bg-warning/5", text: "text-warning/70", border: "border-warning/20" },
}

function RankLabel({ pct }: { pct: number | null }) {
  if (pct == null) return null
  const p = Math.round(pct * 100)
  if (p <= 10) return <span className="text-[10px] font-medium text-market-up">领涨 前{p}%</span>
  if (p <= 70) return <span className="text-[10px] text-muted-foreground">跟涨 前{p}%</span>
  return <span className="text-[10px] text-market-down">滞涨 前{p}%</span>
}

function AdvanceDeclineBar({ up, down }: { up: number; down: number }) {
  const total = up + down
  if (total === 0) return null
  const upPct = (up / total) * 100
  return (
    <div className="flex items-center gap-1.5">
      <div className="h-1.5 flex-1 flex rounded-full overflow-hidden bg-muted">
        <div className="h-full bg-market-up/80 transition-all" style={{ width: `${upPct}%` }} />
        <div className="h-full bg-market-down/80 transition-all" style={{ width: `${100 - upPct}%` }} />
      </div>
      <span className="text-[10px] text-muted-foreground shrink-0">
        <span className="text-market-up">{up}</span>/<span className="text-market-down">{down}</span>
      </span>
    </div>
  )
}

function ConceptMiniCard({
  concept,
  onClick,
}: {
  concept: StockConceptItem
  onClick: () => void
}) {
  const pct = concept.pct_change
  const isUp = pct > 0
  const isDown = pct < 0
  const hasLiveData = pct !== 0 || concept.up_count > 0 || concept.down_count > 0

  const pctColor = isUp ? "text-market-up" : isDown ? "text-market-down" : "text-muted-foreground"
  const borderHover = isUp
    ? "hover:border-market-up/30 hover:bg-market-up/5"
    : isDown
      ? "hover:border-market-down/30 hover:bg-market-down/5"
      : "hover:border-border hover:bg-muted/50"

  return (
    <button
      onClick={onClick}
      className={`rounded-lg border bg-card p-2.5 text-left transition-colors cursor-pointer ${borderHover}`}
    >
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-medium truncate">{concept.name}</span>
        <Badge variant="outline" className="text-[9px] px-1 py-0 h-4 font-normal">
          {concept.code}
        </Badge>
      </div>

      {hasLiveData ? (
        <>
          {/* Large pct change */}
          <div className={`text-lg font-bold font-numeric ${pctColor} mb-1.5`}>
            {isUp && <TrendingUp className="inline h-4 w-4 mr-0.5" />}
            {isDown && <TrendingDown className="inline h-4 w-4 mr-0.5" />}
            {!isUp && !isDown && <Minus className="inline h-4 w-4 mr-0.5" />}
            {pct > 0 ? "+" : ""}{pct.toFixed(2)}%
          </div>

          {/* Advance/decline bar */}
          <AdvanceDeclineBar up={concept.up_count} down={concept.down_count} />

          {/* Limit-up / limit-down badges */}
          {(concept.zt_count > 0 || concept.dt_count > 0) && (
            <div className="flex items-center gap-1.5 mt-1">
              {concept.zt_count > 0 && (
                <span className="text-[10px] font-medium text-market-up bg-market-up/10 px-1 rounded">
                  涨停 {concept.zt_count}
                </span>
              )}
              {concept.dt_count > 0 && (
                <span className="text-[10px] font-medium text-market-down bg-market-down/10 px-1 rounded">
                  跌停 {concept.dt_count}
                </span>
              )}
            </div>
          )}

          {/* Rank within concept */}
          <div className="mt-1.5">
            <RankLabel pct={concept.stock_rank_pct} />
          </div>
        </>
      ) : (
        <div className="text-xs text-muted-foreground mt-1">行情数据暂不可用</div>
      )}
    </button>
  )
}

export function ConceptTagBar({ symbol }: ConceptTagBarProps) {
  const { data, isLoading } = useStockConcepts(symbol)
  const [selectedConcept, setSelectedConcept] = useState<StockConceptItem | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)

  if (isLoading) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <Skeleton className="h-5 w-24" />
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
          </div>
        </CardContent>
      </Card>
    )
  }

  if (!data || data.concepts.length === 0) return null

  const resonance = data.resonance
  const resonanceCfg = RESONANCE_CONFIG[resonance.level]

  const handleConceptClick = (concept: StockConceptItem) => {
    setSelectedConcept(concept)
    setSheetOpen(true)
  }

  return (
    <>
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-medium flex items-center gap-1.5">
              <Layers className="h-4 w-4 text-muted-foreground" />
              概念板块
            </CardTitle>
            <div className="flex items-center gap-2">
              {data.industry && (
                <Badge variant="secondary" className="text-xs">
                  {data.industry}
                </Badge>
              )}
              <span className="text-xs text-muted-foreground">{data.concepts.length} 个概念</span>
            </div>
          </div>
        </CardHeader>

        <CardContent className="space-y-3">
          {/* Resonance banner */}
          {resonanceCfg && (
            <div className={`rounded-md border px-3 py-2 flex items-center gap-2 ${resonanceCfg.bg} ${resonanceCfg.border}`}>
              <Sparkles className={`h-4 w-4 ${resonanceCfg.text}`} />
              <span className={`text-sm font-medium ${resonanceCfg.text}`}>
                {resonanceCfg.label}
              </span>
              <span className={`text-xs ${resonanceCfg.text} opacity-80`}>
                — {resonance.concepts.length} 个概念同步走强
                {resonance.top_driver && ` · 主力: ${resonance.top_driver}`}
                {resonance.rank_in_driver && ` (${resonance.rank_in_driver})`}
              </span>
            </div>
          )}

          {/* Concept mini-card grid */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
            {data.concepts.map((c) => (
              <ConceptMiniCard
                key={c.code}
                concept={c}
                onClick={() => handleConceptClick(c)}
              />
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Detail panel */}
      <ConceptDetailSheet
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        concept={selectedConcept}
        currentSymbol={symbol}
      />
    </>
  )
}
