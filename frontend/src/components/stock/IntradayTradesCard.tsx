import { useIntradayTrades } from "@/hooks/useStocks"
import { Loader2 } from "lucide-react"
import type { RealtimeSnapshot, IntradayTradesStats, TickRecord } from "@/types/stock"
import { selectTradesStats, selectRecentTicks } from "@/hooks/useRealtimeSnapshot"
import { cn } from "@/lib/utils"
import { formatVolume } from "@/lib/formatters"

interface IntradayTradesCardProps {
  symbol: string
  snapshot?: RealtimeSnapshot
}

const DIRECTION_LABEL: Record<string, string> = { buy: "买", sell: "卖", neutral: "中" }

export function IntradayTradesCard({ symbol, snapshot }: IntradayTradesCardProps) {
  const fallback = useIntradayTrades(symbol)

  // Use snapshot data when available, otherwise fall back to standalone hook
  const stats: IntradayTradesStats | null | undefined =
    snapshot ? selectTradesStats(snapshot) : fallback.data
  const recentTicks: TickRecord[] = snapshot ? selectRecentTicks(snapshot) : []
  const isLoading = !snapshot && fallback.isLoading
  const isHistorical = snapshot?.trades?.is_historical ?? stats?.is_historical ?? false

  if (isLoading) {
    return (
      <div className="rounded-lg border bg-card p-4">
        <h4 className="text-sm font-medium mb-3">买卖盘统计</h4>
        <div className="flex items-center justify-center h-16 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin mr-2" />
          <span className="text-xs">加载中...</span>
        </div>
      </div>
    )
  }

  if (!stats || stats.total_volume === 0) {
    return (
      <div className="rounded-lg border bg-card p-4">
        <h4 className="text-sm font-medium mb-3">买卖盘统计</h4>
        <p className="text-xs text-muted-foreground text-center py-3">暂无买卖盘数据</p>
      </div>
    )
  }

  const buyPct = Math.round(stats.buy_ratio * 100)
  const sellPct = Math.round(stats.sell_ratio * 100)
  const neutralPct = 100 - buyPct - sellPct

  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-sm font-medium">买卖盘统计</h4>
        {isHistorical && (
          <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">最近交易日</span>
        )}
      </div>

      {/* Ratio bar */}
      <div className="flex h-3 rounded-full overflow-hidden mb-3">
        {buyPct > 0 && (
          <div
            className="bg-market-up transition-all duration-500"
            style={{ width: `${buyPct}%` }}
          />
        )}
        {neutralPct > 0 && (
          <div
            className="bg-muted-foreground/60 transition-all duration-500"
            style={{ width: `${neutralPct}%` }}
          />
        )}
        {sellPct > 0 && (
          <div
            className="bg-market-down transition-all duration-500"
            style={{ width: `${sellPct}%` }}
          />
        )}
      </div>

      {/* Labels */}
      <div className="grid grid-cols-3 gap-2 text-xs">
        <div>
          <div className="text-market-up font-medium">买盘 {buyPct}%</div>
          <div className="text-muted-foreground font-numeric">{formatVolume(stats.buy_volume)}</div>
        </div>
        <div className="text-center">
          <div className="text-muted-foreground font-medium">中性 {neutralPct}%</div>
          <div className="text-muted-foreground font-numeric">{formatVolume(stats.neutral_volume)}</div>
        </div>
        <div className="text-right">
          <div className="text-market-down font-medium">卖盘 {sellPct}%</div>
          <div className="text-muted-foreground font-numeric">{formatVolume(stats.sell_volume)}</div>
        </div>
      </div>

      {/* Recent ticks table */}
      {recentTicks.length > 0 && (
        <>
          <div className="border-t my-3" />
          <h5 className="text-xs font-medium text-muted-foreground mb-2">近期逐笔成交</h5>
          <div className="max-h-48 overflow-y-auto">
            <table className="w-full text-[11px]">
              <thead className="sticky top-0 bg-card">
                <tr className="text-muted-foreground border-b">
                  <th className="text-left font-medium py-1 pr-2">时间</th>
                  <th className="text-right font-medium py-1 px-2">价格</th>
                  <th className="text-right font-medium py-1 px-2">数量</th>
                  <th className="text-right font-medium py-1 pl-2">方向</th>
                </tr>
              </thead>
              <tbody>
                {recentTicks.map((tick, i) => (
                  <tr key={i} className="border-b border-border/50 last:border-0">
                    <td className="py-0.5 pr-2 text-muted-foreground font-numeric">{tick.time}</td>
                    <td className="py-0.5 px-2 text-right font-numeric">{tick.price.toFixed(2)}</td>
                    <td className="py-0.5 px-2 text-right font-numeric">{tick.volume}</td>
                    <td className={cn(
                      "py-0.5 pl-2 text-right font-medium",
                      tick.direction === "buy" && "text-market-up",
                      tick.direction === "sell" && "text-market-down",
                      tick.direction === "neutral" && "text-muted-foreground",
                    )}>
                      {DIRECTION_LABEL[tick.direction] ?? "中"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
