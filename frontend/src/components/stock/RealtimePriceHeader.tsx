import { useEffect, useRef, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { formatPrice, formatPercent, formatVolume, cn } from "@/lib/utils"
import { MARKET_COLORS, BOARD_LABELS } from "@/lib/constants"
import type { RealtimeQuote } from "@/types/market"
import type { StockDetail } from "@/types/stock"

interface RealtimePriceHeaderProps {
  stock: StockDetail
  realtimeQuote?: RealtimeQuote | null
}

export function RealtimePriceHeader({ stock, realtimeQuote }: RealtimePriceHeaderProps) {
  const [flash, setFlash] = useState<"up" | "down" | null>(null)
  const prevPriceRef = useRef<number | null>(null)

  const price = realtimeQuote?.price ?? stock.close
  const change = realtimeQuote?.change ?? stock.change
  const pctChange = realtimeQuote?.pct_change ?? stock.pct_change
  const volume = realtimeQuote?.volume ?? stock.volume
  const open = realtimeQuote?.open ?? stock.open
  const high = realtimeQuote?.high ?? stock.high
  const low = realtimeQuote?.low ?? stock.low
  const prevClose = realtimeQuote?.prev_close

  const direction = (change != null && !Number.isNaN(change)) ? (change > 0 ? "up" : change < 0 ? "down" : "flat") : "flat"
  const color = direction === "up" ? MARKET_COLORS.up : direction === "down" ? MARKET_COLORS.down : MARKET_COLORS.flat

  useEffect(() => {
    if (price != null && prevPriceRef.current != null && price !== prevPriceRef.current) {
      setFlash(price > prevPriceRef.current ? "up" : "down")
      const timer = setTimeout(() => setFlash(null), 800)
      return () => clearTimeout(timer)
    }
    if (price != null) prevPriceRef.current = price
  }, [price])

  return (
    <div className={cn("space-y-2", flash === "up" && "flash-up", flash === "down" && "flash-down")}>
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-bold">{stock.name}</h1>
        <span className="text-sm text-muted-foreground font-numeric">{stock.symbol}</span>
        <Badge variant="outline" className="text-xs">{BOARD_LABELS[stock.board] || stock.board}</Badge>
        {realtimeQuote && <span className="live-dot" title="实时数据" />}
      </div>

      <div className="flex items-baseline gap-4">
        <span className="text-3xl font-bold font-numeric" style={{ color }}>
          {price != null ? formatPrice(price) : "--"}
        </span>
        <div className="font-numeric" style={{ color }}>
          <span className="text-lg font-medium">
            {change != null && !Number.isNaN(change) ? (change > 0 ? "+" : "") + change.toFixed(2) : "--"}
          </span>
          <span className="text-lg font-medium ml-2">
            {pctChange != null ? formatPercent(pctChange) : "--"}
          </span>
        </div>
      </div>

      <div className="flex items-center gap-6 text-xs text-muted-foreground font-numeric">
        <span>开 {open != null ? formatPrice(open) : "--"}</span>
        <span>高 <span style={{ color: MARKET_COLORS.up }}>{high != null ? formatPrice(high) : "--"}</span></span>
        <span>低 <span style={{ color: MARKET_COLORS.down }}>{low != null ? formatPrice(low) : "--"}</span></span>
        {prevClose != null && <span>昨收 {formatPrice(prevClose)}</span>}
        <span>量 {volume != null ? formatVolume(volume) : "--"}</span>
      </div>
    </div>
  )
}
