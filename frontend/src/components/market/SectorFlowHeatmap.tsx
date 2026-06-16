import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Loader2, TrendingUp } from "lucide-react"
import { useSectorFlow, useSectorHeatmap } from "@/hooks/useCapitalFlow"
import type { SectorFlowItem, HeatmapItem } from "@/types/capital-flow"

function FlowColor({ value }: { value: number }) {
  if (value > 0) return <span className="text-market-up">+{value.toFixed(2)}</span>
  if (value < 0) return <span className="text-market-down">{value.toFixed(2)}</span>
  return <span className="text-muted-foreground">0.00</span>
}

function HeatmapGrid({ items }: { items: HeatmapItem[] }) {
  if (!items.length) {
    return <p className="text-xs text-muted-foreground py-4 text-center">暂无热力图数据</p>
  }

  const maxAbs = Math.max(...items.map((i) => Math.abs(i.color_value)), 0.01)

  return (
    <div className="grid grid-cols-4 md:grid-cols-5 lg:grid-cols-6 gap-1">
      {items.map((item) => {
        const intensity = Math.abs(item.color_value) / maxAbs
        const pct = Math.round(Math.max(15, Math.min(80, intensity * 100)))
        const bg =
          item.color_value > 0
            ? `color-mix(in oklch, var(--color-market-up) ${pct}%, transparent)`
            : item.color_value < 0
              ? `color-mix(in oklch, var(--color-market-down) ${pct}%, transparent)`
              : "var(--color-muted)"

        return (
          <div
            key={item.name}
            className="rounded-md p-2 text-center text-[10px] leading-tight border border-transparent hover:border-foreground/20 transition-colors cursor-default"
            style={{ backgroundColor: bg }}
            title={`${item.name}: 净流入 ${item.net_inflow.toFixed(2)}亿 | 涨跌 ${item.change_pct.toFixed(2)}%`}
          >
            <div className="font-medium truncate">{item.name}</div>
            <div className="font-mono tabular-nums mt-0.5">
              {item.net_inflow > 0 ? "+" : ""}
              {item.net_inflow.toFixed(1)}亿
            </div>
          </div>
        )
      })}
    </div>
  )
}

function RankingTable({ items }: { items: SectorFlowItem[] }) {
  if (!items.length) {
    return <p className="text-xs text-muted-foreground py-4 text-center">暂无数据</p>
  }

  return (
    <div className="space-y-1">
      <div className="grid grid-cols-12 gap-2 text-[10px] text-muted-foreground px-2 py-1">
        <div className="col-span-4">板块名称</div>
        <div className="col-span-2 text-right">涨跌幅</div>
        <div className="col-span-3 text-right">净流入(亿)</div>
        <div className="col-span-3 text-right">主力净流入</div>
      </div>
      {items.slice(0, 20).map((item, idx) => (
        <div
          key={item.sector_name}
          className="grid grid-cols-12 gap-2 text-xs px-2 py-1.5 rounded-md hover:bg-accent transition-colors"
        >
          <div className="col-span-4 flex items-center gap-1.5">
            <span className="text-[10px] text-muted-foreground w-4">{idx + 1}</span>
            <span className="truncate">{item.sector_name}</span>
          </div>
          <div className="col-span-2 text-right font-mono tabular-nums">
            {item.change_pct != null ? (
              <span className={item.change_pct > 0 ? "text-market-up" : item.change_pct < 0 ? "text-market-down" : ""}>
                {item.change_pct > 0 ? "+" : ""}
                {item.change_pct.toFixed(2)}%
              </span>
            ) : (
              "—"
            )}
          </div>
          <div className="col-span-3 text-right font-mono tabular-nums">
            <FlowColor value={item.net_inflow} />
          </div>
          <div className="col-span-3 text-right font-mono tabular-nums">
            <FlowColor value={item.main_net_inflow} />
          </div>
        </div>
      ))}
    </div>
  )
}

export function SectorFlowTab() {
  const [sectorType, setSectorType] = useState<"industry" | "concept">("industry")
  const [period, setPeriod] = useState("today")

  const { data: heatmapData, isLoading: heatmapLoading } = useSectorHeatmap()
  const { data: rankingData, isLoading: rankingLoading } = useSectorFlow(sectorType, period)

  return (
    <div className="space-y-4">
      {/* Heatmap card */}
      <Card>
        <CardHeader className="py-3 px-4">
          <CardTitle className="text-title flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-accent-primary" />
            板块资金热力图
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-3">
          {heatmapLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <HeatmapGrid items={heatmapData?.items ?? []} />
          )}
        </CardContent>
      </Card>

      {/* Ranking card */}
      <Card>
        <CardHeader className="py-3 px-4">
          <div className="flex items-center justify-between">
            <CardTitle className="text-title">板块资金排行</CardTitle>
            <div className="flex items-center gap-2">
              <Tabs value={sectorType} onValueChange={(v) => setSectorType(v as "industry" | "concept")}>
                <TabsList className="h-7">
                  <TabsTrigger value="industry" className="text-xs h-6 px-2">行业</TabsTrigger>
                  <TabsTrigger value="concept" className="text-xs h-6 px-2">概念</TabsTrigger>
                </TabsList>
              </Tabs>
              <Tabs value={period} onValueChange={setPeriod}>
                <TabsList className="h-7">
                  <TabsTrigger value="today" className="text-xs h-6 px-2">今日</TabsTrigger>
                  <TabsTrigger value="3d" className="text-xs h-6 px-2">3日</TabsTrigger>
                  <TabsTrigger value="5d" className="text-xs h-6 px-2">5日</TabsTrigger>
                </TabsList>
              </Tabs>
            </div>
          </div>
        </CardHeader>
        <CardContent className="px-4 pb-3 space-y-2">
          {rankingData?.interpretation && (
            <p className="text-xs text-muted-foreground leading-relaxed border-l-2 border-accent-primary/40 pl-2">
              {rankingData.interpretation}
            </p>
          )}
          {rankingLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <RankingTable items={rankingData?.items ?? []} />
          )}
        </CardContent>
      </Card>
    </div>
  )
}
