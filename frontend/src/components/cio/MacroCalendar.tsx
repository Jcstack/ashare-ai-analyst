/** Macro economic calendar — latest releases with surprise detection. */

import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Loader2 } from "lucide-react"
import { useMacroCalendar } from "@/hooks/useIntelligence"
import type { MacroReleaseItem } from "@/api/intelligence"

function SurpriseCell({ surprise }: { surprise: number | null }) {
  if (surprise === null) return <span className="text-muted-foreground">—</span>
  const isPositive = surprise > 0
  const isSignificant = Math.abs(surprise) > 0.1
  return (
    <span
      className={`font-numeric ${
        isSignificant
          ? isPositive
            ? "text-market-up font-medium"
            : "text-market-down font-medium"
          : "text-muted-foreground"
      }`}
    >
      {surprise > 0 ? "+" : ""}
      {surprise.toFixed(2)}
    </span>
  )
}

function ReleaseRow({ item }: { item: MacroReleaseItem }) {
  return (
    <tr className="border-b border-border/50 text-xs">
      <td className="py-1.5 pr-2">
        <div className="flex items-center gap-1.5">
          <Badge variant="outline" className="text-[10px] px-1">
            {item.country}
          </Badge>
          <span>{item.indicator}</span>
        </div>
      </td>
      <td className="py-1.5 text-muted-foreground">{item.date}</td>
      <td className="py-1.5 font-numeric text-right">
        {item.actual?.toFixed(2) ?? "—"}
      </td>
      <td className="py-1.5 font-numeric text-right text-muted-foreground">
        {item.forecast?.toFixed(2) ?? "—"}
      </td>
      <td className="py-1.5 font-numeric text-right text-muted-foreground">
        {item.previous?.toFixed(2) ?? "—"}
      </td>
      <td className="py-1.5 text-right">
        <SurpriseCell surprise={item.surprise} />
      </td>
    </tr>
  )
}

export function MacroCalendar() {
  const { data, isLoading } = useMacroCalendar()

  return (
    <Card>
      <CardContent className="py-4 px-5 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-caption font-medium">宏观日历</span>
          {data && (
            <span className="text-[10px] text-muted-foreground">
              {data.total_releases} 条数据
            </span>
          )}
        </div>

        {isLoading && (
          <div className="flex items-center justify-center py-4 gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" />
            加载宏观数据...
          </div>
        )}

        {data && data.total_releases > 0 && (
          <>
            {/* Surprises highlight */}
            {data.surprises.length > 0 && (
              <div className="rounded-md bg-warning/10 p-2 space-y-1">
                <span className="text-[10px] font-medium text-warning">
                  超预期信号
                </span>
                {data.surprises.map((s, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    <Badge variant="outline" className="text-[10px] px-1">
                      {s.country}
                    </Badge>
                    <span>{s.indicator}</span>
                    <SurpriseCell surprise={s.surprise} />
                  </div>
                ))}
              </div>
            )}

            {/* Full table */}
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="text-[10px] text-muted-foreground border-b">
                    <th className="text-left py-1 font-normal">指标</th>
                    <th className="text-left py-1 font-normal">日期</th>
                    <th className="text-right py-1 font-normal">实际</th>
                    <th className="text-right py-1 font-normal">预期</th>
                    <th className="text-right py-1 font-normal">前值</th>
                    <th className="text-right py-1 font-normal">偏差</th>
                  </tr>
                </thead>
                <tbody>
                  {[...data.china, ...data.us].map((item, i) => (
                    <ReleaseRow key={i} item={item} />
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {data && data.total_releases === 0 && (
          <p className="text-xs text-muted-foreground py-2">暂无宏观数据</p>
        )}
      </CardContent>
    </Card>
  )
}
