import { Skeleton } from "@/components/ui/skeleton"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { useStockDragonTiger } from "@/hooks/useMarket"
import { ListX } from "lucide-react"
import { formatAmount, formatPercent } from "@/lib/formatters"

interface StockDragonTigerProps {
  symbol: string
}

export function StockDragonTiger({ symbol }: StockDragonTigerProps) {
  const { data, isLoading } = useStockDragonTiger(symbol)

  if (isLoading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-16 w-full" />
        ))}
      </div>
    )
  }

  if (!data?.length) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12 text-muted-foreground gap-3">
          <ListX className="h-10 w-10 opacity-40" />
          <p className="text-sm">近 30 日未上榜龙虎榜</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">龙虎榜记录 (近30日)</CardTitle>
      </CardHeader>
      <CardContent>
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
              {data.map((item, i) => (
                <tr key={`${item.date}-${i}`} className="border-b data-row-hover">
                  <td className="py-2 pr-4 text-sm font-mono">{item.date || "-"}</td>
                  <td
                    className={`py-2 pr-4 text-right col-numeric ${
                      (item.pct_change ?? 0) >= 0 ? "text-market-up" : "text-market-down"
                    }`}
                  >
                    {formatPercent(item.pct_change)}
                  </td>
                  <td
                    className={`py-2 pr-4 text-right col-numeric ${
                      (item.net_buy ?? 0) >= 0 ? "text-market-up" : "text-market-down"
                    }`}
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
    </Card>
  )
}
