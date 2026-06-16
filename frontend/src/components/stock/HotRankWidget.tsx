import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Flame } from "lucide-react"
import { useHotRank } from "@/hooks/useNews"
import { useNavigate } from "react-router-dom"
import { formatPercent } from "@/lib/utils"
import { MARKET_COLORS } from "@/lib/constants"

const RANK_COLORS = ["#f59e0b", "#9ca3af", "#d97706"]

export function HotRankWidget() {
  const { data, isLoading, dataUpdatedAt } = useHotRank()
  const navigate = useNavigate()

  const maxPct = Math.max(...(data ?? []).map((d) => Math.abs(d.pct_change ?? 0)), 1)

  return (
    <Card>
      <CardContent className="p-3">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Flame className="h-4 w-4 text-warning" />
            <span className="text-title">热门排行</span>
          </div>
          {dataUpdatedAt && (
            <span className="text-micro text-muted-foreground">
              {new Date(dataUpdatedAt).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
        </div>

        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-7 w-full" />
            ))}
          </div>
        ) : (
          <div className="space-y-0.5">
            {(data ?? []).slice(0, 10).map((item, i) => {
              const color = item.pct_change != null
                ? item.pct_change > 0 ? MARKET_COLORS.up : item.pct_change < 0 ? MARKET_COLORS.down : MARKET_COLORS.flat
                : MARKET_COLORS.flat
              const barWidth = item.pct_change != null ? (Math.abs(item.pct_change) / maxPct) * 100 : 0

              return (
                <div
                  key={item.symbol}
                  className="relative flex items-center gap-2 px-1.5 py-1.5 rounded cursor-pointer transition-colors hover:bg-accent/50"
                  onClick={() => navigate(`/stock/${item.symbol}`)}
                >
                  {/* Percentage bar background */}
                  <div
                    className="absolute inset-0 rounded opacity-[0.06]"
                    style={{
                      background: color,
                      width: `${Math.min(barWidth, 100)}%`,
                    }}
                  />
                  <span
                    className="text-xs font-bold w-5 text-center relative"
                    style={{ color: i < 3 ? RANK_COLORS[i] : undefined }}
                  >
                    {item.rank || i + 1}
                  </span>
                  <span className="text-xs flex-1 truncate relative">{item.name}</span>
                  <span className="price-sm relative" style={{ color }}>
                    {item.pct_change != null ? formatPercent(item.pct_change) : "--"}
                  </span>
                </div>
              )
            })}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
