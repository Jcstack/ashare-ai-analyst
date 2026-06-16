import { Badge } from "@/components/ui/badge"
import { formatPrice, formatPercent, getPriceDirection } from "@/lib/utils"
import { MARKET_COLORS, BOARD_LABELS } from "@/lib/constants"
import type { StockDetail } from "@/types/stock"

interface PriceHeaderProps {
  stock: StockDetail
}

export function PriceHeader({ stock }: PriceHeaderProps) {
  const dir = getPriceDirection(stock.change)
  const color = MARKET_COLORS[dir]

  return (
    <div className="flex items-start justify-between">
      <div>
        <div className="flex items-center gap-3 mb-1">
          <h1 className="text-2xl font-bold">{stock.name}</h1>
          <span className="text-lg text-muted-foreground">{stock.symbol}</span>
          <Badge variant="secondary">{BOARD_LABELS[stock.board] ?? stock.board}</Badge>
        </div>
        <div className="flex items-baseline gap-4">
          <span
            className="text-4xl font-bold font-mono tabular-nums"
            style={{ color }}
          >
            {formatPrice(stock.close)}
          </span>
          <span className="text-xl font-mono tabular-nums" style={{ color }}>
            {stock.change != null && stock.change > 0 ? "+" : ""}
            {formatPrice(stock.change)}
          </span>
          <span className="text-xl font-mono tabular-nums" style={{ color }}>
            {formatPercent(stock.pct_change)}
          </span>
        </div>
        <p className="text-sm text-muted-foreground mt-1">
          {stock.date ?? "--"}
        </p>
      </div>
    </div>
  )
}
