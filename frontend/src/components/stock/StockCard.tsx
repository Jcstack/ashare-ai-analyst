import { Link } from "react-router-dom"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { formatPrice, formatPercent, formatVolume, getPriceDirection, cn } from "@/lib/utils"
import { MARKET_COLORS, BOARD_LABELS } from "@/lib/constants"
import type { WatchlistItem } from "@/types/stock"

interface StockCardProps {
  stock: WatchlistItem
}

const directionBg = {
  up: "bg-market-up/5",
  down: "bg-market-down/5",
  flat: "",
} as const

export function StockCard({ stock }: StockCardProps) {
  const dir = getPriceDirection(stock.change)
  const color = MARKET_COLORS[dir]

  return (
    <Link to={`/stock/${stock.symbol}`}>
      <Card
        className={cn(
          "cursor-pointer hover:shadow-lg hover:-translate-y-0.5 transition-all duration-200",
          directionBg[dir]
        )}
      >
        <CardContent className="p-4">
          <div className="flex items-start justify-between mb-3">
            <div>
              <p className="font-semibold">{stock.name}</p>
              <p className="text-sm text-muted-foreground">{stock.symbol}</p>
            </div>
            <Badge variant="secondary">{BOARD_LABELS[stock.board] ?? stock.board}</Badge>
          </div>
          <div className="space-y-1">
            <p
              className="text-3xl font-bold font-mono tabular-nums"
              style={{ color }}
            >
              {formatPrice(stock.close)}
            </p>
            <div className="flex items-center gap-2 text-sm font-mono tabular-nums">
              <span style={{ color }}>
                {stock.change != null && stock.change > 0 ? "+" : ""}
                {formatPrice(stock.change)}
              </span>
              <span style={{ color }}>{formatPercent(stock.pct_change)}</span>
            </div>
            <p className="text-xs text-muted-foreground">
              成交量: {stock.volume != null ? formatVolume(stock.volume) : "--"}
            </p>
          </div>
        </CardContent>
      </Card>
    </Link>
  )
}
