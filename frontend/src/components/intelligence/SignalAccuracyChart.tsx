/** Signal accuracy trend chart — Recharts line chart showing T+3/T+5 accuracy. */

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useAccuracyHistory } from "@/hooks/useMarketIntelligence"
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts"
import { TrendingUp } from "lucide-react"

export function SignalAccuracyChart({
  signalType,
  windowDays = 30,
}: {
  signalType?: string
  windowDays?: number
}) {
  const { data, isLoading } = useAccuracyHistory({
    signal_type: signalType,
    granularity: "daily",
    window_days: windowDays,
  })

  if (isLoading) {
    return (
      <Card>
        <CardContent className="py-4">
          <Skeleton className="h-48 w-full rounded-lg" />
        </CardContent>
      </Card>
    )
  }

  if (!data || data.data.length === 0) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">
          暂无准确率历史数据
        </CardContent>
      </Card>
    )
  }

  const chartData = data.data
    .filter((d) => d.accuracy_t3 != null || d.accuracy_t5 != null)
    .map((d) => ({
      date: d.date.slice(5), // MM-DD
      "T+3": d.accuracy_t3 != null ? +(d.accuracy_t3 * 100).toFixed(1) : null,
      "T+5": d.accuracy_t5 != null ? +(d.accuracy_t5 * 100).toFixed(1) : null,
      samples: d.sample_count,
    }))

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <TrendingUp className="h-4 w-4" />
          信号准确率趋势
          <span className="text-xs text-muted-foreground font-normal">
            {data.signal_type === "ALL" ? "全部类型" : data.signal_type} · {data.window_days}天
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
              stroke="hsl(var(--border))"
            />
            <YAxis
              tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
              stroke="hsl(var(--border))"
              domain={[0, 100]}
              tickFormatter={(v) => `${v}%`}
            />
            <Tooltip
              contentStyle={{
                background: "hsl(var(--card))",
                border: "1px solid hsl(var(--border))",
                borderRadius: 6,
                fontSize: 12,
              }}
              formatter={(value) => [`${value}%`]}
            />
            <Legend
              wrapperStyle={{ fontSize: 11 }}
            />
            <Line
              type="monotone"
              dataKey="T+3"
              stroke="hsl(var(--primary))"
              strokeWidth={2}
              dot={false}
              connectNulls
            />
            <Line
              type="monotone"
              dataKey="T+5"
              stroke="hsl(142 70% 45%)"
              strokeWidth={2}
              dot={false}
              connectNulls
            />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
