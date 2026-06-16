import { BarChart3, TrendingUp, Flame, Building2 } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import type { DragonTigerItem, LimitUpItem } from "@/types/market"
import { formatAmount } from "@/lib/formatters"

interface DragonTigerSummaryProps {
  data: DragonTigerItem[]
}

export function DragonTigerSummary({ data }: DragonTigerSummaryProps) {
  const totalStocks = new Set(data.map((d) => d.symbol)).size
  const totalNetBuy = data.reduce((s, d) => s + (d.net_buy ?? 0), 0)
  const topBuy = data.reduce(
    (best, d) => ((d.net_buy ?? 0) > (best.net_buy ?? -Infinity) ? d : best),
    data[0],
  )

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
      <Card>
        <CardContent className="flex items-center gap-3 py-3 px-4">
          <BarChart3 className="h-5 w-5 text-accent-primary shrink-0" />
          <div>
            <p className="text-xs text-muted-foreground">上榜股票数</p>
            <p className="text-lg font-bold tabular-nums">{totalStocks}</p>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="flex items-center gap-3 py-3 px-4">
          <TrendingUp className="h-5 w-5 shrink-0" style={{ color: totalNetBuy >= 0 ? "var(--color-market-up)" : "var(--color-market-down)" }} />
          <div>
            <p className="text-xs text-muted-foreground">净买入总额</p>
            <p
              className="text-lg font-bold tabular-nums"
              style={{ color: totalNetBuy >= 0 ? "var(--color-market-up)" : "var(--color-market-down)" }}
            >
              {formatAmount(totalNetBuy)}
            </p>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="flex items-center gap-3 py-3 px-4">
          <Flame className="h-5 w-5 text-market-up shrink-0" />
          <div>
            <p className="text-xs text-muted-foreground">最大净买入</p>
            {topBuy ? (
              <p className="text-sm font-bold truncate">
                {topBuy.name}
                <span className="text-xs text-muted-foreground ml-1">
                  {formatAmount(topBuy.net_buy ?? 0)}
                </span>
              </p>
            ) : (
              <p className="text-sm">--</p>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

interface LimitUpSummaryProps {
  data: LimitUpItem[]
}

export function LimitUpSummary({ data }: LimitUpSummaryProps) {
  const totalCount = data.length
  const firstBoard = data.filter((d) => !d.consecutive || d.consecutive <= 1).length
  const secondBoard = data.filter((d) => d.consecutive === 2).length
  const thirdPlus = data.filter((d) => (d.consecutive ?? 0) >= 3).length

  // Top industry by count
  const industryCounts: Record<string, number> = {}
  for (const d of data) {
    const ind = d.industry || "其他"
    industryCounts[ind] = (industryCounts[ind] || 0) + 1
  }
  const topIndustry = Object.entries(industryCounts).sort((a, b) => b[1] - a[1])[0]

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
      <Card>
        <CardContent className="flex items-center gap-3 py-3 px-4">
          <TrendingUp className="h-5 w-5 text-market-up shrink-0" />
          <div>
            <p className="text-xs text-muted-foreground">涨停数量</p>
            <p className="text-lg font-bold tabular-nums text-market-up">{totalCount}</p>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="flex items-center gap-3 py-3 px-4">
          <Flame className="h-5 w-5 text-warning shrink-0" />
          <div>
            <p className="text-xs text-muted-foreground">连板分布</p>
            <div className="flex gap-2 text-xs font-medium tabular-nums">
              <span>首板 {firstBoard}</span>
              <span className="text-warning">2连 {secondBoard}</span>
              <span className="text-market-up">3+连 {thirdPlus}</span>
            </div>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="flex items-center gap-3 py-3 px-4">
          <Building2 className="h-5 w-5 text-accent-primary shrink-0" />
          <div>
            <p className="text-xs text-muted-foreground">最热行业</p>
            {topIndustry ? (
              <p className="text-sm font-bold truncate">
                {topIndustry[0]}
                <span className="text-xs text-muted-foreground ml-1">({topIndustry[1]}只)</span>
              </p>
            ) : (
              <p className="text-sm">--</p>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
