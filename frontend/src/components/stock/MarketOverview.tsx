import { Card, CardContent } from "@/components/ui/card"
import { TrendingUp, TrendingDown, Minus, Loader2 } from "lucide-react"
import { formatPercent, formatPrice } from "@/lib/utils"
import { MARKET_COLORS } from "@/lib/constants"
import { useMarketIndices } from "@/hooks/useMarket"

export function MarketOverview() {
  const { data: indices = [], isLoading } = useMarketIndices()

  const fallbackNames = ["上证指数", "深证成指", "创业板指", "科创50"]
  const displayItems = indices.length > 0
    ? indices
    : fallbackNames.map((name) => ({ name, code: "", price: 0, change: 0, pct_change: 0 }))

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      {displayItems.map((idx) => {
        const hasData = indices.length > 0
        const direction = hasData
          ? idx.pct_change > 0 ? "up" : idx.pct_change < 0 ? "down" : "flat"
          : "flat"
        const color = direction === "up" ? MARKET_COLORS.up : direction === "down" ? MARKET_COLORS.down : MARKET_COLORS.flat
        const Icon = direction === "up" ? TrendingUp : direction === "down" ? TrendingDown : Minus

        return (
          <Card key={idx.name} className="overflow-hidden group card-hover">
            <CardContent className="p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-caption text-muted-foreground">{idx.name}</span>
                {isLoading ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
                ) : (
                  <Icon className="h-4 w-4 transition-transform group-hover:scale-110" style={{ color }} />
                )}
              </div>
              <div className="price-hero" style={{ color }}>
                {hasData ? formatPrice(idx.price) : "--"}
              </div>
              <div className="flex items-center gap-2 mt-1.5">
                <span className="price-sm font-semibold" style={{ color }}>
                  {hasData ? formatPercent(idx.pct_change) : "--"}
                </span>
                <span className="price-sm opacity-60" style={{ color }}>
                  {hasData ? (idx.change > 0 ? "+" : "") + idx.change.toFixed(2) : ""}
                </span>
              </div>
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}
