import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { ListX, ChevronDown, Activity, TrendingUp, Award, BarChart2, Info } from "lucide-react"
import { useDragonTigerSeats, useDragonTigerStats } from "@/hooks/useAnalysis"
import { useStockDragonTiger } from "@/hooks/useMarket"
import { DragonTigerAICard } from "./DragonTigerAICard"
import { SeatBreakdown } from "./SeatBreakdown"
import { cn, formatVolume } from "@/lib/utils"
import { formatAmount, formatPercent } from "@/lib/formatters"

interface StockDragonTigerDeepProps {
  symbol: string
}

export function StockDragonTigerDeep({ symbol }: StockDragonTigerDeepProps) {
  const { data: history, isLoading: loadingHistory } = useStockDragonTiger(symbol)
  const { data: seats, isLoading: loadingSeats } = useDragonTigerSeats(symbol)
  const { data: stats, isLoading: loadingStats } = useDragonTigerStats(symbol)
  const [historyOpen, setHistoryOpen] = useState(false)

  const allLoading = loadingHistory && loadingSeats && loadingStats
  const hasHistory = history && history.length > 0
  const hasSeats = seats && seats.length > 0
  const hasAnyData = hasHistory || hasSeats || (stats && stats.appearances_3m > 0)

  // Detect today's dragon tiger record
  const today = new Date().toISOString().slice(0, 10) // YYYY-MM-DD
  const todayRecord = hasHistory ? history.find((item) => item.date === today) : null
  const pastHistory = hasHistory ? history.filter((item) => item.date !== today) : []

  // Full skeleton only when everything is loading
  if (allLoading) {
    return (
      <div className="space-y-3">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-[72px] rounded-lg" />
          ))}
        </div>
        <Skeleton className="h-40 rounded-lg" />
        <Skeleton className="h-32 rounded-lg" />
      </div>
    )
  }

  // Empty state: no dragon tiger records at all (and done loading)
  if (!hasAnyData && !loadingHistory && !loadingSeats && !loadingStats) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12 text-muted-foreground gap-3">
          <ListX className="h-10 w-10 opacity-40" />
          <p className="text-sm">暂无龙虎榜记录</p>
          <p className="text-xs text-muted-foreground/70">该股票近期未出现在龙虎榜上</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-3">
      {/* Stats cards row */}
      {loadingStats && !stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-[72px] rounded-lg" />
          ))}
        </div>
      )}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatsCard
            icon={<Activity className="h-4 w-4 text-accent-primary" />}
            label="近3月上榜"
            value={`${stats.appearances_3m} 次`}
          />
          <StatsCard
            icon={<BarChart2 className="h-4 w-4 text-warning" />}
            label="机构净买入"
            value={formatVolume(Math.abs(stats.institution_net_buy))}
            valueColor={stats.institution_net_buy >= 0 ? "text-market-up" : "text-market-down"}
            prefix={stats.institution_net_buy >= 0 ? "+" : "-"}
          />
          <StatsCard
            icon={<TrendingUp className="h-4 w-4 text-info" />}
            label="5日平均收益"
            value={`${stats.avg_return_5d >= 0 ? "+" : ""}${stats.avg_return_5d.toFixed(2)}%`}
            valueColor={stats.avg_return_5d >= 0 ? "text-market-up" : "text-market-down"}
          />
          <StatsCard
            icon={<Award className="h-4 w-4 text-info" />}
            label="5日胜率"
            value={`${(stats.win_rate_5d * 100).toFixed(0)}%`}
            valueColor={stats.win_rate_5d >= 0.5 ? "text-market-up" : "text-market-down"}
          />
        </div>
      )}

      {/* Today's dragon tiger highlight */}
      {todayRecord ? (
        <Card className="border-warning/40 bg-warning/5">
          <CardHeader className="py-3">
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-warning" />
              <CardTitle className="text-sm text-warning">今日上榜</CardTitle>
              <Badge variant="outline" className="text-[10px] border-warning/40 text-warning">
                {todayRecord.date}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div>
                <span className="text-[10px] text-muted-foreground">涨跌幅</span>
                <p className={cn("text-sm font-semibold font-numeric", (todayRecord.pct_change ?? 0) >= 0 ? "text-market-up" : "text-market-down")}>
                  {formatPercent(todayRecord.pct_change)}
                </p>
              </div>
              <div>
                <span className="text-[10px] text-muted-foreground">净买入</span>
                <p className={cn("text-sm font-semibold font-numeric", (todayRecord.net_buy ?? 0) >= 0 ? "text-market-up" : "text-market-down")}>
                  {formatAmount(todayRecord.net_buy)}
                </p>
              </div>
              <div>
                <span className="text-[10px] text-muted-foreground">买入额</span>
                <p className="text-sm font-semibold font-numeric text-market-up">
                  {formatAmount(todayRecord.buy_amount)}
                </p>
              </div>
              <div>
                <span className="text-[10px] text-muted-foreground">卖出额</span>
                <p className="text-sm font-semibold font-numeric text-market-down">
                  {formatAmount(todayRecord.sell_amount)}
                </p>
              </div>
            </div>
            {todayRecord.reason && (
              <div className="mt-2 pt-2 border-t border-warning/20">
                <Badge variant="outline" className="text-xs border-warning/40">
                  {todayRecord.reason}
                </Badge>
              </div>
            )}
          </CardContent>
        </Card>
      ) : (
        <div className="flex items-center gap-2 text-xs text-muted-foreground px-1">
          <Info className="h-3.5 w-3.5 shrink-0" />
          <span>龙虎榜数据于每交易日收盘后更新 (~16:00)</span>
        </div>
      )}

      {/* AI analysis card */}
      <DragonTigerAICard symbol={symbol} />

      {/* Seat breakdown */}
      {loadingSeats && !seats && <Skeleton className="h-32 rounded-lg" />}
      {hasSeats && <SeatBreakdown seats={seats} />}

      {/* Collapsible history table */}
      {pastHistory.length > 0 && (
        <Collapsible open={historyOpen} onOpenChange={setHistoryOpen}>
          <Card>
            <CardHeader className="py-3">
              <CollapsibleTrigger className="w-full">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm">
                    龙虎榜历史记录 ({pastHistory.length})
                  </CardTitle>
                  <ChevronDown
                    className={cn(
                      "h-4 w-4 text-muted-foreground transition-transform",
                      historyOpen && "rotate-180",
                    )}
                  />
                </div>
              </CollapsibleTrigger>
            </CardHeader>

            <CollapsibleContent>
              <CardContent className="pt-0">
                <div className="overflow-x-auto">
                  <table className="w-full data-table">
                    <thead>
                      <tr className="border-b text-left text-muted-foreground">
                        <th className="py-2 pr-4">日期</th>
                        <th className="py-2 pr-4 text-right">涨跌幅</th>
                        <th className="py-2 pr-4 text-right">净买入</th>
                        <th className="py-2 pr-4 text-right">买入额</th>
                        <th className="py-2 pr-4 text-right">卖出额</th>
                        <th className="py-2 pr-4">上榜原因</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pastHistory.map((item, i) => (
                        <tr key={`${item.date}-${i}`} className="border-b data-row-hover">
                          <td className="py-2 pr-4 text-sm font-mono">{item.date || "-"}</td>
                          <td
                            className={cn(
                              "py-2 pr-4 text-right col-numeric",
                              (item.pct_change ?? 0) >= 0 ? "text-market-up" : "text-market-down",
                            )}
                          >
                            {formatPercent(item.pct_change)}
                          </td>
                          <td
                            className={cn(
                              "py-2 pr-4 text-right col-numeric",
                              (item.net_buy ?? 0) >= 0 ? "text-market-up" : "text-market-down",
                            )}
                          >
                            {formatAmount(item.net_buy)}
                          </td>
                          <td className="py-2 pr-4 text-right col-numeric text-market-up">
                            {formatAmount(item.buy_amount)}
                          </td>
                          <td className="py-2 pr-4 text-right col-numeric text-market-down">
                            {formatAmount(item.sell_amount)}
                          </td>
                          <td className="py-2 pr-4 max-w-[220px]">
                            {item.reason ? (
                              <Badge variant="outline" className="text-xs truncate max-w-full">
                                {item.reason}
                              </Badge>
                            ) : (
                              <span className="text-xs text-muted-foreground">-</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </CollapsibleContent>
          </Card>
        </Collapsible>
      )}
    </div>
  )
}

/** Small stats card used in the top row */
interface StatsCardProps {
  icon: React.ReactNode
  label: string
  value: string
  valueColor?: string
  prefix?: string
}

function StatsCard({ icon, label, value, valueColor, prefix }: StatsCardProps) {
  return (
    <Card>
      <CardContent className="p-3 flex flex-col gap-1.5">
        <div className="flex items-center gap-1.5">
          {icon}
          <span className="text-[10px] text-muted-foreground">{label}</span>
        </div>
        <p className={cn("text-lg font-semibold font-numeric", valueColor)}>
          {prefix && <span>{prefix}</span>}
          {value}
        </p>
      </CardContent>
    </Card>
  )
}
