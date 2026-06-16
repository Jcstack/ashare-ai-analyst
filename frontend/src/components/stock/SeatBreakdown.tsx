import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { formatVolume, cn } from "@/lib/utils"
import type { DragonTigerSeatItem } from "@/types/analysis"

/** Seat type icon mapping */
const SEAT_TYPE_ICONS: Record<string, string> = {
  "\u673A\u6784": "\uD83C\uDFDB\uFE0F",       // 机构
  "\u77E5\u540D\u6E38\u8D44": "\uD83D\uDD25",   // 知名游资
  "\u666E\u901A\u8425\u4E1A\u90E8": "\uD83C\uDFE2", // 普通营业部
}

function getSeatIcon(seatType: string): string {
  for (const [key, icon] of Object.entries(SEAT_TYPE_ICONS)) {
    if (seatType.includes(key)) return icon
  }
  return "\uD83C\uDFE2" // Default: office building
}

/** Seat type badge color */
function getSeatTypeClass(seatType: string): string {
  if (seatType.includes("\u673A\u6784")) return "text-warning"
  if (seatType.includes("\u6E38\u8D44")) return "text-warning"
  return "text-muted-foreground"
}

interface SeatBreakdownProps {
  seats: DragonTigerSeatItem[]
}

export function SeatBreakdown({ seats }: SeatBreakdownProps) {
  // Split seats into buy side (positive net) and sell side (negative net)
  const buySide = seats.filter((s) => (s.net_amount ?? 0) > 0)
    .sort((a, b) => (b.net_amount ?? 0) - (a.net_amount ?? 0))
  const sellSide = seats.filter((s) => (s.net_amount ?? 0) < 0)
    .sort((a, b) => (a.net_amount ?? 0) - (b.net_amount ?? 0))
  // Neutral seats (net_amount === 0 or null) go to buy side for display
  const neutralSeats = seats.filter((s) => s.net_amount === 0 || s.net_amount === null)

  if (seats.length === 0) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-8 text-muted-foreground">
          <p className="text-sm">暂无席位明细数据</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader className="py-3">
        <CardTitle className="text-sm">买卖席位对比</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Buy side */}
          <div className="space-y-2">
            <div className="flex items-center gap-2 mb-2">
              <span className="inline-block w-3 h-3 rounded-full bg-market-up" />
              <span className="text-sm font-semibold text-market-up">
                买入方 ({buySide.length + neutralSeats.length})
              </span>
            </div>
            {[...buySide, ...neutralSeats].map((seat, i) => (
              <SeatRow key={`buy-${i}`} seat={seat} side="buy" />
            ))}
            {buySide.length === 0 && neutralSeats.length === 0 && (
              <p className="text-xs text-muted-foreground py-2">暂无买入席位</p>
            )}
          </div>

          {/* Sell side */}
          <div className="space-y-2">
            <div className="flex items-center gap-2 mb-2">
              <span className="inline-block w-3 h-3 rounded-full bg-market-down" />
              <span className="text-sm font-semibold text-market-down">
                卖出方 ({sellSide.length})
              </span>
            </div>
            {sellSide.map((seat, i) => (
              <SeatRow key={`sell-${i}`} seat={seat} side="sell" />
            ))}
            {sellSide.length === 0 && (
              <p className="text-xs text-muted-foreground py-2">暂无卖出席位</p>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

interface SeatRowProps {
  seat: DragonTigerSeatItem
  side: "buy" | "sell"
}

function SeatRow({ seat, side }: SeatRowProps) {
  const icon = getSeatIcon(seat.seat_type)
  const typeClass = getSeatTypeClass(seat.seat_type)
  const amount = side === "buy" ? seat.buy_amount : seat.sell_amount
  const netAmount = seat.net_amount ?? 0

  return (
    <div className="flex items-center gap-2 rounded-md border px-3 py-2 hover:bg-accent/50 transition-colors">
      <span className="text-base shrink-0" role="img" aria-label={seat.seat_type}>
        {icon}
      </span>
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium truncate" title={seat.seat_name}>
          {seat.seat_name}
        </p>
        <p className={cn("text-[10px]", typeClass)}>
          {seat.seat_type}
        </p>
      </div>
      <div className="text-right shrink-0 space-y-0.5">
        {amount != null && (
          <p className={cn(
            "text-xs font-numeric font-medium",
            side === "buy" ? "text-market-up" : "text-market-down",
          )}>
            {formatVolume(Math.abs(amount))}
          </p>
        )}
        {netAmount !== 0 && (
          <p className={cn(
            "text-[10px] font-numeric",
            netAmount > 0 ? "text-market-up" : "text-market-down",
          )}>
            净{netAmount > 0 ? "买" : "卖"} {formatVolume(Math.abs(netAmount))}
          </p>
        )}
      </div>
    </div>
  )
}
