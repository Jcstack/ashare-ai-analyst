/** Performance dashboard — win rates, avg returns, charts.
 *
 * Per PRD v28.0 FR-REC062: Performance tracking dashboard.
 */

import { useState } from "react"
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { TrendingUp, Target, BarChart3, Award } from "lucide-react"
import { usePerformance, useStyles } from "@/hooks/useRecommendations"
import type { WindowStats } from "@/types/recommendation"

const WINDOW_LABELS: Record<string, string> = {
  t1: "T+1",
  t3: "T+3",
  t5: "T+5",
  t10: "T+10",
}

const DAYS_OPTIONS = [
  { label: "30天", value: 30 },
  { label: "90天", value: 90 },
  { label: "180天", value: 180 },
  { label: "全部", value: 365 },
]

const STYLE_LABELS: Record<string, string> = {
  value: "价值投资",
  growth: "成长投资",
  momentum: "动量交易",
  swing: "波段交易",
  dividend: "红利收息",
  sector: "板块轮动",
}

export function PerformanceDashboard() {
  const [selectedStyle, setSelectedStyle] = useState<string | undefined>(undefined)
  const [days, setDays] = useState(90)
  const { data: stylesData } = useStyles()
  const { data: stats, isLoading } = usePerformance({
    style: selectedStyle,
    days,
  })

  const styles = stylesData?.styles ?? []

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-lg" />
          ))}
        </div>
        <Skeleton className="h-64 rounded-lg" />
      </div>
    )
  }

  const windows = stats?.windows ?? ({} as Record<string, WindowStats>)
  const totalRecs = stats?.total_recs ?? 0

  // Build chart data for win rates across windows
  const chartData = Object.entries(windows).map(([key, w]) => {
    const ws = w as WindowStats
    return {
      name: WINDOW_LABELS[key] || key,
      win_rate: ws.win_rate ?? 0,
      avg_return: ws.avg_return ?? 0,
      filled: ws.filled,
    }
  })

  const hasData = totalRecs > 0 && chartData.some((d) => d.filled > 0)

  return (
    <div className="space-y-6">
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <Badge
          variant={!selectedStyle ? "default" : "outline"}
          className="cursor-pointer text-xs"
          onClick={() => setSelectedStyle(undefined)}
        >
          全部
        </Badge>
        {styles.map((s) => (
          <Badge
            key={s.key}
            variant={selectedStyle === s.key ? "default" : "outline"}
            className="cursor-pointer text-xs"
            onClick={() => setSelectedStyle(s.key)}
          >
            {s.label}
          </Badge>
        ))}
        <span className="mx-2 text-muted-foreground">|</span>
        {DAYS_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            onClick={() => setDays(opt.value)}
            className={`px-2 py-0.5 text-xs rounded transition-colors ${
              days === opt.value
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {!hasData ? (
        <Card>
          <CardContent className="py-16 text-center">
            <BarChart3 className="h-10 w-10 text-muted-foreground/40 mx-auto mb-3" />
            <p className="text-sm text-muted-foreground">
              暂无表现数据，推荐产生后系统将自动回填 T+N 实际表现
            </p>
          </CardContent>
        </Card>
      ) : (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Card>
              <CardContent className="p-4 text-center">
                <div className="text-[10px] text-muted-foreground flex items-center justify-center gap-1">
                  <Award className="h-3 w-3" />
                  总推荐数
                </div>
                <div className="text-xl font-bold font-numeric mt-1">{totalRecs}</div>
              </CardContent>
            </Card>
            {(["t3", "t5", "t10"] as const).map((key) => {
              const w = (windows as Record<string, WindowStats>)[key]
              if (!w) return null
              const winRate = w.win_rate
              return (
                <Card key={key}>
                  <CardContent className="p-4 text-center">
                    <div className="text-[10px] text-muted-foreground flex items-center justify-center gap-1">
                      <Target className="h-3 w-3" />
                      {WINDOW_LABELS[key]} 胜率
                    </div>
                    <div
                      className={`text-xl font-bold font-numeric mt-1 ${
                        winRate != null && winRate >= 50 ? "text-market-up" : winRate != null ? "text-market-down" : ""
                      }`}
                    >
                      {winRate != null ? `${winRate}%` : "--"}
                    </div>
                    <div className="text-[10px] text-muted-foreground mt-0.5">
                      {w.filled > 0
                        ? `${w.wins}/${w.filled} 样本`
                        : "暂无数据"}
                    </div>
                  </CardContent>
                </Card>
              )
            })}
          </div>

          {/* Win rate bar chart */}
          <Card>
            <CardHeader className="py-3">
              <CardTitle className="text-sm flex items-center gap-1.5">
                <TrendingUp className="h-4 w-4 text-primary" />
                {selectedStyle
                  ? `${STYLE_LABELS[selectedStyle] || selectedStyle} 表现统计`
                  : "各窗口期表现统计"}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={240}>
                <BarChart
                  data={chartData}
                  margin={{ top: 10, left: 10, right: 30, bottom: 10 }}
                >
                  <CartesianGrid strokeDasharray="3 3" opacity={0.1} />
                  <XAxis dataKey="name" tick={{ fontSize: 12 }} tickLine={false} />
                  <YAxis
                    yAxisId="left"
                    tick={{ fontSize: 10 }}
                    tickFormatter={(v: number) => `${v}%`}
                    domain={[0, 100]}
                  />
                  <YAxis
                    yAxisId="right"
                    orientation="right"
                    tick={{ fontSize: 10 }}
                    tickFormatter={(v: number) => `${v}%`}
                  />
                  <Tooltip
                    formatter={(value, name) => {
                      const v = Number(value ?? 0)
                      if (name === "胜率") return [`${v.toFixed(1)}%`, name]
                      if (name === "平均收益") return [`${v.toFixed(2)}%`, name]
                      return [v, name]
                    }}
                  />
                  <Bar
                    yAxisId="left"
                    dataKey="win_rate"
                    fill="#4FC3F7"
                    name="胜率"
                    radius={[4, 4, 0, 0]}
                  />
                  <Bar
                    yAxisId="right"
                    dataKey="avg_return"
                    fill="#FFB74D"
                    name="平均收益"
                    radius={[4, 4, 0, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}
