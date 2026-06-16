import { useMemo, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Sparkles,
  Layers,
  TrendingUp,
  TrendingDown,
  ArrowUpDown,
  Lightbulb,
  AlertTriangle,
} from "lucide-react"
import { useStockConcepts } from "@/hooks/useConcept"
import type { StockConceptItem, StockConceptsResult } from "@/types/concept"
import { formatAmount } from "@/lib/formatters"

interface ConceptAnalysisTabProps {
  symbol: string
}

// ---- Overview Card ----

function ConceptOverviewCard({ data }: { data: StockConceptsResult }) {
  const { resonance, concepts, industry } = data

  const upConcepts = concepts.filter((c) => c.pct_change > 0).length
  const downConcepts = concepts.filter((c) => c.pct_change < 0).length
  const flatConcepts = concepts.length - upConcepts - downConcepts
  const avgPct = concepts.length > 0
    ? concepts.reduce((sum, c) => sum + c.pct_change, 0) / concepts.length
    : 0

  // Check if all concepts lack live performance data (push2 blocked)
  const hasLiveData = concepts.some(
    (c) => c.pct_change !== 0 || c.up_count > 0 || c.down_count > 0,
  )

  const resonanceColors: Record<string, string> = {
    strong: "bg-market-up/10 text-market-up border-market-up/30",
    moderate: "bg-warning/10 text-warning border-warning/30",
    weak: "bg-warning/5 text-warning/70 border-warning/20",
    none: "bg-muted text-muted-foreground border-border",
  }

  const resonanceLabels: Record<string, string> = {
    strong: "强共振",
    moderate: "中共振",
    weak: "弱共振",
    none: "无共振",
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium flex items-center gap-1.5">
          <Layers className="h-4 w-4 text-muted-foreground" />
          概念总览
        </CardTitle>
      </CardHeader>
      <CardContent>
        {!hasLiveData && (
          <div className="rounded-md border border-border bg-muted/30 px-3 py-2 mb-3 flex items-center gap-2">
            <Layers className="h-4 w-4 text-muted-foreground shrink-0" />
            <span className="text-xs text-muted-foreground">板块实时行情暂不可用，已展示概念归属信息</span>
          </div>
        )}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <div className="rounded-lg bg-muted/50 p-3 text-center">
            <div className="text-[10px] text-muted-foreground">行业</div>
            <div className="text-sm font-medium mt-1">{industry || "-"}</div>
          </div>
          <div className="rounded-lg bg-muted/50 p-3 text-center">
            <div className="text-[10px] text-muted-foreground">关联概念</div>
            <div className="text-sm font-medium mt-1">{concepts.length} 个</div>
          </div>
          {hasLiveData ? (
            <>
              <div className="rounded-lg bg-muted/50 p-3 text-center">
                <div className="text-[10px] text-muted-foreground">上涨/平盘/下跌</div>
                <div className="text-sm mt-1">
                  <span className="text-market-up font-medium">{upConcepts}</span>
                  <span className="text-muted-foreground mx-0.5">/</span>
                  <span className="text-muted-foreground">{flatConcepts}</span>
                  <span className="text-muted-foreground mx-0.5">/</span>
                  <span className="text-market-down font-medium">{downConcepts}</span>
                </div>
              </div>
              <div className="rounded-lg bg-muted/50 p-3 text-center">
                <div className="text-[10px] text-muted-foreground">概念平均涨幅</div>
                <div className={`text-sm font-medium font-numeric mt-1 ${avgPct > 0 ? "text-market-up" : avgPct < 0 ? "text-market-down" : "text-muted-foreground"}`}>
                  {avgPct > 0 ? "+" : ""}{avgPct.toFixed(2)}%
                </div>
              </div>
              <div className={`rounded-lg border p-3 text-center ${resonanceColors[resonance.level]}`}>
                <div className="text-[10px] opacity-70">共振状态</div>
                <div className="text-sm font-medium mt-1 flex items-center justify-center gap-1">
                  <Sparkles className="h-3.5 w-3.5" />
                  {resonanceLabels[resonance.level]}
                </div>
              </div>
            </>
          ) : (
            <div className="rounded-lg bg-muted/50 p-3 text-center col-span-3">
              <div className="text-xs text-muted-foreground">概念名称已加载，实时行情数据暂不可用</div>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

// ---- Comparison Table ----

type SortKey = "pct_change" | "amount" | "up_ratio" | "stock_rank_pct"

function ConceptComparisonTable({ concepts }: { concepts: StockConceptItem[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("pct_change")
  const [sortAsc, setSortAsc] = useState(false)

  const sorted = useMemo(() => {
    return [...concepts].sort((a, b) => {
      let av: number, bv: number
      if (sortKey === "up_ratio") {
        const aTotal = a.up_count + a.down_count
        const bTotal = b.up_count + b.down_count
        av = aTotal > 0 ? a.up_count / aTotal : 0
        bv = bTotal > 0 ? b.up_count / bTotal : 0
      } else if (sortKey === "stock_rank_pct") {
        av = a.stock_rank_pct ?? 1
        bv = b.stock_rank_pct ?? 1
      } else {
        av = (a as unknown as Record<string, number>)[sortKey] ?? 0
        bv = (b as unknown as Record<string, number>)[sortKey] ?? 0
      }
      return sortAsc ? av - bv : bv - av
    })
  }, [concepts, sortKey, sortAsc])

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortAsc(!sortAsc)
    } else {
      setSortKey(key)
      setSortAsc(false)
    }
  }

  const SortHeader = ({ label, field }: { label: string; field: SortKey }) => (
    <button
      onClick={() => toggleSort(field)}
      className="flex items-center gap-0.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
    >
      {label}
      <ArrowUpDown className={`h-3 w-3 ${sortKey === field ? "text-foreground" : ""}`} />
    </button>
  )

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">概念对比</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b">
                <th className="text-left py-2 px-2 font-normal text-muted-foreground">概念</th>
                <th className="text-right py-2 px-2"><SortHeader label="涨跌幅" field="pct_change" /></th>
                <th className="text-right py-2 px-2"><SortHeader label="上涨率" field="up_ratio" /></th>
                <th className="text-right py-2 px-2"><SortHeader label="成交额" field="amount" /></th>
                <th className="text-center py-2 px-2">涨跌</th>
                <th className="text-right py-2 px-2"><SortHeader label="个股排名" field="stock_rank_pct" /></th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((c) => {
                const total = c.up_count + c.down_count
                const upRatio = total > 0 ? ((c.up_count / total) * 100).toFixed(0) : "-"
                const pctColor = c.pct_change > 0 ? "text-market-up" : c.pct_change < 0 ? "text-market-down" : "text-muted-foreground"
                const rankPct = c.stock_rank_pct != null ? Math.round(c.stock_rank_pct * 100) : null

                return (
                  <tr key={c.code} className="border-b last:border-0 hover:bg-muted/30 transition-colors">
                    <td className="py-2 px-2">
                      <span className="font-medium">{c.name}</span>
                      <span className="text-[10px] text-muted-foreground ml-1">{c.code}</span>
                    </td>
                    <td className={`text-right py-2 px-2 font-numeric font-medium ${pctColor}`}>
                      {c.pct_change > 0 ? "+" : ""}{c.pct_change.toFixed(2)}%
                    </td>
                    <td className="text-right py-2 px-2 font-numeric">{upRatio}%</td>
                    <td className="text-right py-2 px-2 font-numeric">{formatAmount(c.amount)}</td>
                    <td className="py-2 px-2">
                      <div className="flex items-center justify-center gap-0.5">
                        <span className="text-market-up">{c.up_count}</span>
                        <span className="text-muted-foreground">/</span>
                        <span className="text-market-down">{c.down_count}</span>
                      </div>
                    </td>
                    <td className="text-right py-2 px-2">
                      {rankPct != null ? (
                        <Badge
                          variant="outline"
                          className={`text-[10px] ${
                            rankPct <= 10 ? "text-market-up border-market-up/30" :
                            rankPct > 70 ? "text-market-down border-market-down/30" :
                            "text-muted-foreground"
                          }`}
                        >
                          前{rankPct}%
                        </Badge>
                      ) : "-"}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}

// ---- Performance Bar Chart (horizontal SVG) ----

function ConceptPerformanceChart({ concepts }: { concepts: StockConceptItem[] }) {
  const sorted = useMemo(() => [...concepts].sort((a, b) => b.pct_change - a.pct_change), [concepts])

  if (sorted.length === 0) return null

  const maxAbs = Math.max(...sorted.map((c) => Math.abs(c.pct_change)), 0.01)
  const barH = 24
  const barGap = 4
  const nameW = 90
  const chartW = 400
  const pctLabelW = 60
  const rankW = 40
  const totalW = nameW + chartW + pctLabelW + rankW
  const centerX = nameW + chartW / 2
  const svgH = sorted.length * (barH + barGap) + 8

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">概念表现对比</CardTitle>
      </CardHeader>
      <CardContent>
        <svg viewBox={`0 0 ${totalW} ${svgH}`} className="w-full" preserveAspectRatio="xMidYMin meet">
          {/* Center line */}
          <line x1={centerX} y1={0} x2={centerX} y2={svgH} stroke="currentColor" opacity="0.1" strokeWidth="1" />

          {sorted.map((c, i) => {
            const y = i * (barH + barGap) + 4
            const bw = (Math.abs(c.pct_change) / maxAbs) * (chartW / 2 - 4)
            const isUp = c.pct_change >= 0
            const barX = isUp ? centerX : centerX - bw
            const fillColor = isUp ? "var(--color-market-up)" : "var(--color-market-down)"
            const rankPct = c.stock_rank_pct != null ? Math.round(c.stock_rank_pct * 100) : null

            return (
              <g key={c.code}>
                {/* Name */}
                <text x={nameW - 4} y={y + barH / 2 + 4} textAnchor="end" fontSize="10" className="fill-foreground">
                  {c.name.length > 6 ? c.name.slice(0, 6) + "…" : c.name}
                </text>
                {/* Bar */}
                <rect x={barX} y={y + 2} width={Math.max(bw, 1)} height={barH - 4} rx={3} fill={fillColor} opacity={0.7} />
                {/* Pct label */}
                <text
                  x={nameW + chartW + 4}
                  y={y + barH / 2 + 4}
                  textAnchor="start"
                  fontSize="10"
                  className={isUp ? "fill-market-up" : "fill-market-down"}
                  fontFamily="monospace"
                >
                  {isUp ? "+" : ""}{c.pct_change.toFixed(2)}%
                </text>
                {/* Rank dot */}
                {rankPct != null && (
                  <text
                    x={nameW + chartW + pctLabelW + 4}
                    y={y + barH / 2 + 4}
                    textAnchor="start"
                    fontSize="9"
                    className={`${rankPct <= 10 ? "fill-market-up" : rankPct > 70 ? "fill-market-down" : "fill-muted-foreground"}`}
                  >
                    {rankPct}%
                  </text>
                )}
              </g>
            )
          })}
        </svg>
      </CardContent>
    </Card>
  )
}

// ---- Cross-concept Insight Card ----

function ConceptInsightCard({ data }: { data: StockConceptsResult }) {
  const { concepts, resonance } = data

  const insights = useMemo(() => {
    const result: { type: "driver" | "divergence" | "lagging" | "info"; icon: typeof Lightbulb; text: string }[] = []

    // Driver concept
    if (resonance.top_driver) {
      const driverConcept = concepts.find((c) => c.name === resonance.top_driver)
      const pct = driverConcept?.pct_change
      result.push({
        type: "driver",
        icon: TrendingUp,
        text: `主驱动板块「${resonance.top_driver}」${pct != null ? ` 涨幅 ${pct > 0 ? "+" : ""}${pct.toFixed(2)}%` : ""}，个股${resonance.rank_in_driver || "跟涨"}。`,
      })
    }

    // Divergence check: some concepts up, some down significantly
    const upConcepts = concepts.filter((c) => c.pct_change > 1)
    const downConcepts = concepts.filter((c) => c.pct_change < -1)
    if (upConcepts.length >= 2 && downConcepts.length >= 1) {
      result.push({
        type: "divergence",
        icon: AlertTriangle,
        text: `板块分歧: ${upConcepts.length} 个概念上涨 >1%，${downConcepts.length} 个下跌 >1%。多空因素交织，需关注主线切换。`,
      })
    }

    // Lagging concepts: stock in bottom 30% of a rising concept
    const lagging = concepts.filter(
      (c) => c.pct_change > 1 && c.stock_rank_pct != null && c.stock_rank_pct > 0.7,
    )
    if (lagging.length > 0) {
      const names = lagging.map((c) => c.name).join("、")
      result.push({
        type: "lagging",
        icon: TrendingDown,
        text: `在「${names}」板块中排名靠后 (后30%)，若板块持续走强，存在补涨逻辑。`,
      })
    }

    // General info
    if (concepts.length > 0 && result.length === 0) {
      const best = [...concepts].sort((a, b) => b.pct_change - a.pct_change)[0]
      result.push({
        type: "info",
        icon: Lightbulb,
        text: `关联 ${concepts.length} 个概念板块，表现最强的是「${best.name}」(${best.pct_change > 0 ? "+" : ""}${best.pct_change.toFixed(2)}%)。`,
      })
    }

    return result
  }, [concepts, resonance])

  if (insights.length === 0) return null

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium flex items-center gap-1.5">
          <Lightbulb className="h-4 w-4 text-muted-foreground" />
          概念洞察
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {insights.map((insight, i) => {
            const Icon = insight.icon
            const colors: Record<string, string> = {
              driver: "text-market-up bg-market-up/10",
              divergence: "text-warning bg-warning/10",
              lagging: "text-info bg-info/10",
              info: "text-muted-foreground bg-muted/50",
            }
            return (
              <div key={i} className={`flex items-start gap-2 rounded-md p-2.5 ${colors[insight.type]}`}>
                <Icon className="h-4 w-4 mt-0.5 shrink-0" />
                <span className="text-xs leading-relaxed">{insight.text}</span>
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}

// ---- Concept Tag Cloud (fallback when no live data) ----

function ConceptTagCloud({ concepts, industry }: { concepts: StockConceptItem[]; industry: string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium flex items-center gap-1.5">
          <Layers className="h-4 w-4 text-muted-foreground" />
          关联概念板块
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-wrap gap-2">
          {industry && (
            <Badge variant="secondary" className="text-xs border-primary/20 bg-primary/5">
              {industry}
            </Badge>
          )}
          {concepts.map((c) => (
            <Badge key={c.code || c.name} variant="outline" className="text-xs">
              {c.name}
            </Badge>
          ))}
        </div>
        <p className="text-[11px] text-muted-foreground mt-3">
          概念归属来源于东方财富 F10 核心概念数据。板块实时行情需板块行情接口支持，当前网络环境下暂不可用。
        </p>
      </CardContent>
    </Card>
  )
}

// ---- Main Tab Component ----

export function ConceptAnalysisTab({ symbol }: ConceptAnalysisTabProps) {
  const { data, isLoading } = useStockConcepts(symbol)

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-64 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    )
  }

  if (!data || data.concepts.length === 0) {
    return (
      <div className="text-center py-16 text-muted-foreground">
        <Layers className="h-8 w-8 mx-auto mb-3 opacity-50" />
        <p className="text-sm">暂无概念板块数据</p>
        <p className="text-xs mt-1">该股票可能尚未关联概念板块</p>
      </div>
    )
  }

  // Check if we have real-time board performance data (push2 available)
  const hasLiveData = data.concepts.some(
    (c) => c.pct_change !== 0 || c.up_count > 0 || c.down_count > 0,
  )

  // No live data: show simplified concept tag view instead of misleading zero-value tables
  if (!hasLiveData) {
    return (
      <div className="space-y-4">
        <ConceptOverviewCard data={data} />
        <ConceptTagCloud concepts={data.concepts} industry={data.industry} />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <ConceptOverviewCard data={data} />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ConceptComparisonTable concepts={data.concepts} />
        <ConceptPerformanceChart concepts={data.concepts} />
      </div>
      <ConceptInsightCard data={data} />
    </div>
  )
}
