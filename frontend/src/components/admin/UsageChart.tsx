import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

interface ProviderData {
  total_calls?: number
  total_cost_usd?: number
  daily?: { date: string; calls: number; cost_usd: number }[]
}

interface UsageChartProps {
  providers: Record<string, unknown>
}

export function UsageChart({ providers }: UsageChartProps) {
  const chartData = Object.entries(providers)
    .map(([name, data]) => {
      const d = data as ProviderData
      return {
        provider: name,
        requests: d?.total_calls ?? 0,
        cost: d?.total_cost_usd ?? 0,
      }
    })
    .filter((d) => d.requests > 0 || d.cost > 0)
    .sort((a, b) => b.requests - a.requests)

  if (chartData.length === 0) {
    return (
      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm">提供商使用统计</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground text-center py-8">暂无使用数据</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader className="py-3">
        <CardTitle className="text-sm">提供商使用统计</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Per-provider stats table */}
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b text-muted-foreground">
                <th className="text-left p-2">提供商</th>
                <th className="text-right p-2">请求数</th>
                <th className="text-right p-2">费用 (USD)</th>
                <th className="text-right p-2">均价/请求</th>
              </tr>
            </thead>
            <tbody>
              {chartData.map((d) => (
                <tr key={d.provider} className="border-b">
                  <td className="p-2 font-medium">{d.provider}</td>
                  <td className="p-2 text-right tabular-nums">{d.requests}</td>
                  <td className="p-2 text-right tabular-nums font-mono">${d.cost.toFixed(4)}</td>
                  <td className="p-2 text-right tabular-nums font-mono text-muted-foreground">
                    ${d.requests > 0 ? (d.cost / d.requests).toFixed(5) : "0"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Bar chart for visual comparison */}
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={chartData} margin={{ top: 10, left: 10, right: 50, bottom: 10 }}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.1} />
            <XAxis dataKey="provider" tick={{ fontSize: 11 }} tickLine={false} interval={0} />
            <YAxis yAxisId="left" tick={{ fontSize: 10 }} />
            <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} tickFormatter={(v: number) => `$${v.toFixed(3)}`} />
            <Tooltip
              formatter={(value, name) => {
                if (name === "费用 (USD)") return [`$${Number(value).toFixed(4)}`, name]
                return [value, name]
              }}
            />
            <Legend />
            <Bar yAxisId="left" dataKey="requests" fill="#4FC3F7" name="请求数" radius={[4, 4, 0, 0]} />
            <Bar yAxisId="right" dataKey="cost" fill="#FFB74D" name="费用 (USD)" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
