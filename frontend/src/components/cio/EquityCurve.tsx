/** Equity curve chart — portfolio value over time from daily snapshots. */

import { Card, CardContent } from "@/components/ui/card"
import { useQuery } from "@tanstack/react-query"
import client from "@/api/client"
import { Loader2 } from "lucide-react"

interface Snapshot {
  date: string
  total_value: number
  total_cost: number
  unrealized_pnl: number
  position_count: number
}

async function fetchEquityCurve(days: number): Promise<{ snapshots: Snapshot[]; count: number }> {
  const { data } = await client.get("/intelligence/equity-curve", { params: { days } })
  return data
}

export function EquityCurve({ days = 90 }: { days?: number }) {
  const { data, isLoading } = useQuery({
    queryKey: ["intelligence", "equity-curve", days],
    queryFn: () => fetchEquityCurve(days),
    staleTime: 5 * 60 * 1000,
  })

  const snapshots = data?.snapshots ?? []

  if (isLoading) {
    return (
      <Card>
        <CardContent className="py-6 flex items-center justify-center text-xs text-muted-foreground gap-2">
          <Loader2 className="h-3 w-3 animate-spin" />
          加载净值曲线...
        </CardContent>
      </Card>
    )
  }

  if (snapshots.length === 0) {
    return (
      <Card>
        <CardContent className="py-6 text-center text-xs text-muted-foreground">
          暂无净值快照数据，收盘后自动采集
        </CardContent>
      </Card>
    )
  }

  const first = snapshots[0]
  const last = snapshots[snapshots.length - 1]
  const totalReturn = first.total_cost > 0
    ? ((last.total_value - first.total_cost) / first.total_cost) * 100
    : 0
  const maxValue = Math.max(...snapshots.map((s) => s.total_value))
  const minValue = Math.min(...snapshots.map((s) => s.total_value))
  const range = maxValue - minValue || 1

  return (
    <Card>
      <CardContent className="py-4 px-5 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-caption font-medium">净值曲线</span>
          <div className="flex items-center gap-3 text-xs">
            <span className="text-muted-foreground">
              {snapshots.length} 日
            </span>
            <span className={`font-numeric ${totalReturn > 0 ? "text-market-up" : totalReturn < 0 ? "text-market-down" : ""}`}>
              {totalReturn > 0 ? "+" : ""}{totalReturn.toFixed(2)}%
            </span>
          </div>
        </div>

        {/* Simple SVG sparkline */}
        <div className="h-24 w-full">
          <svg viewBox={`0 0 ${snapshots.length - 1} 100`} className="w-full h-full" preserveAspectRatio="none">
            <polyline
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              className={totalReturn >= 0 ? "text-market-up" : "text-market-down"}
              points={snapshots
                .map((s, i) => `${i},${100 - ((s.total_value - minValue) / range) * 90 - 5}`)
                .join(" ")}
            />
            {/* Cost baseline */}
            {first.total_cost > 0 && (
              <line
                x1="0"
                y1={100 - ((first.total_cost - minValue) / range) * 90 - 5}
                x2={snapshots.length - 1}
                y2={100 - ((first.total_cost - minValue) / range) * 90 - 5}
                stroke="currentColor"
                strokeWidth="0.5"
                strokeDasharray="2,2"
                className="text-muted-foreground"
              />
            )}
          </svg>
        </div>

        <div className="flex justify-between text-[10px] text-muted-foreground">
          <span>{first.date}</span>
          <span>最新: ¥{last.total_value.toFixed(0)}</span>
          <span>{last.date}</span>
        </div>
      </CardContent>
    </Card>
  )
}
