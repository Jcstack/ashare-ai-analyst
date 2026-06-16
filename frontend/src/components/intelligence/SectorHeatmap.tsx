/** Sector rotation heatmap — Recharts Treemap + rotation table. */

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { useSectorRotation } from "@/hooks/useMarketIntelligence"
import { Treemap, ResponsiveContainer } from "recharts"
import { ArrowUpRight, ArrowDownRight } from "lucide-react"

interface TreemapNode {
  name: string
  size: number
  fill: string
  [key: string]: string | number
}

export function SectorHeatmap() {
  const { data, isLoading } = useSectorRotation()

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-48 w-full rounded-lg" />
        <Skeleton className="h-32 w-full rounded-lg" />
      </div>
    )
  }

  if (!data || data.error || !data.sectors || data.sectors.length === 0) {
    return (
      <div className="py-12 text-center text-sm text-muted-foreground">
        板块轮动数据暂不可用
      </div>
    )
  }

  const treemapData: TreemapNode[] = data.sectors.map((s) => ({
    name: s.name,
    size: Math.abs(s.performance) + 1,
    fill: s.performance > 0
      ? `hsl(142 ${Math.min(70, Math.abs(s.performance) * 10 + 20)}% 40%)`
      : `hsl(0 ${Math.min(70, Math.abs(s.performance) * 10 + 20)}% 45%)`,
  }))

  return (
    <div className="space-y-4">
      {/* Treemap */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            板块热力图
            {data.rotation_direction && (
              <Badge variant="outline" className="text-xs">
                轮动: {data.rotation_direction}
              </Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ResponsiveContainer width="100%" height={220}>
            <Treemap
              data={treemapData}
              dataKey="size"
              aspectRatio={4 / 3}
              stroke="hsl(var(--border))"
              content={<CustomTreemapContent />}
            />
          </ResponsiveContainer>
        </CardContent>
      </Card>

      {/* Leading / Lagging */}
      <div className="grid grid-cols-2 gap-4">
        <Card>
          <CardContent className="py-3 px-4">
            <div className="flex items-center gap-1.5 mb-2">
              <ArrowUpRight className="h-3.5 w-3.5 text-green-500" />
              <span className="text-xs font-medium">领涨板块</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {(data.leading ?? []).map((s) => (
                <Badge key={s} variant="outline" className="text-xs text-green-500 border-green-500/30">
                  {s}
                </Badge>
              ))}
              {(data.leading ?? []).length === 0 && (
                <span className="text-xs text-muted-foreground">无数据</span>
              )}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-3 px-4">
            <div className="flex items-center gap-1.5 mb-2">
              <ArrowDownRight className="h-3.5 w-3.5 text-red-500" />
              <span className="text-xs font-medium">领跌板块</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {(data.lagging ?? []).map((s) => (
                <Badge key={s} variant="outline" className="text-xs text-red-500 border-red-500/30">
                  {s}
                </Badge>
              ))}
              {(data.lagging ?? []).length === 0 && (
                <span className="text-xs text-muted-foreground">无数据</span>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Sector table */}
      <Card>
        <CardContent className="py-3 px-0">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b text-muted-foreground">
                <th className="text-left px-4 py-1.5 font-medium">板块</th>
                <th className="text-right px-4 py-1.5 font-medium">涨幅</th>
                <th className="text-right px-4 py-1.5 font-medium">量变</th>
                <th className="text-right px-4 py-1.5 font-medium">信号</th>
              </tr>
            </thead>
            <tbody>
              {data.sectors.map((s) => (
                <tr key={s.name} className="border-b border-muted/50 hover:bg-muted/30">
                  <td className="px-4 py-1.5">{s.name}</td>
                  <td className={`text-right px-4 py-1.5 font-numeric ${s.performance > 0 ? "text-green-500" : s.performance < 0 ? "text-red-500" : ""}`}>
                    {s.performance > 0 ? "+" : ""}{s.performance.toFixed(2)}%
                  </td>
                  <td className="text-right px-4 py-1.5 font-numeric">
                    {s.volume_change > 0 ? "+" : ""}{s.volume_change.toFixed(1)}%
                  </td>
                  <td className="text-right px-4 py-1.5 font-numeric">{s.signal_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  )
}

/** Custom Treemap cell renderer. */
function CustomTreemapContent(props: any) {
  const { x, y, width, height, name, fill } = props

  if (width < 30 || height < 20) return null

  return (
    <g>
      <rect x={x} y={y} width={width} height={height} fill={fill} rx={2} opacity={0.85} />
      {width > 50 && height > 25 && (
        <text
          x={x + width / 2}
          y={y + height / 2}
          textAnchor="middle"
          dominantBaseline="central"
          className="text-[10px] fill-white"
        >
          {name}
        </text>
      )}
    </g>
  )
}
