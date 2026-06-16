import { Link } from "react-router-dom"
import { Briefcase } from "lucide-react"
import { MARKET_COLORS } from "@/lib/constants"
import { formatPrice, formatPercent } from "@/lib/utils"
import type { Position } from "@/types/portfolio"
import type { RealtimeQuote } from "@/types/market"

interface Props {
  position: Position
  quote: RealtimeQuote | null
}

export function PositionContextCard({ position, quote }: Props) {
  const currentPrice = quote?.price ?? null
  const marketValue = currentPrice != null ? currentPrice * position.shares : null
  const cost = position.costPrice * position.shares
  const pnl = marketValue != null ? marketValue - cost : null
  const pnlPct = cost > 0 && pnl != null ? (pnl / cost) * 100 : null
  const pnlColor =
    pnl != null ? (pnl > 0 ? MARKET_COLORS.up : pnl < 0 ? MARKET_COLORS.down : MARKET_COLORS.flat) : MARKET_COLORS.flat

  const buyDate = position.buyDate ? new Date(position.buyDate) : null
  const holdingDays = buyDate ? Math.floor((Date.now() - buyDate.getTime()) / 86400000) : null

  return (
    <div className="rounded-lg border bg-card p-3 space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-sm font-medium">
          <Briefcase className="h-3.5 w-3.5 text-muted-foreground" />
          我的持仓
        </div>
        <Link
          to="/portfolio"
          className="text-xs text-muted-foreground hover:text-primary transition-colors"
        >
          查看全部持仓
        </Link>
      </div>

      <div className="grid grid-cols-4 gap-3 text-center">
        <div>
          <div className="text-[10px] text-muted-foreground">持仓数量</div>
          <div className="text-sm font-medium font-numeric">{position.shares} 股</div>
        </div>
        <div>
          <div className="text-[10px] text-muted-foreground">成本价</div>
          <div className="text-sm font-medium font-numeric">¥{formatPrice(position.costPrice)}</div>
        </div>
        <div>
          <div className="text-[10px] text-muted-foreground">浮动盈亏</div>
          <div className="text-sm font-medium font-numeric" style={{ color: pnlColor }}>
            {pnl != null ? (
              <>
                {pnl >= 0 ? "+" : ""}¥{formatPrice(Math.abs(pnl))}
                <div className="text-[10px]">({pnlPct != null ? formatPercent(pnlPct) : "--"})</div>
              </>
            ) : (
              "--"
            )}
          </div>
        </div>
        <div>
          <div className="text-[10px] text-muted-foreground">持仓天数</div>
          <div className="text-sm font-medium font-numeric">{holdingDays ?? "--"} 天</div>
        </div>
      </div>

      {(position.note || position.buyDate) && (
        <div className="text-xs text-muted-foreground border-t pt-1.5 flex gap-3">
          {position.buyDate && <span>买入: {position.buyDate}</span>}
          {position.note && <span className="truncate">备注: {position.note}</span>}
        </div>
      )}
    </div>
  )
}
