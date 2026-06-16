import { useState } from "react"
import { Link } from "react-router-dom"
import { Pencil, Trash2, TrendingUp, Plus, Minus, LogOut } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { MoveAnalysisPanel } from "@/components/analysis/MoveAnalysisPanel"
import { useMoveAnalysis } from "@/hooks/useAI"
import { BOARD_LABELS, MARKET_COLORS } from "@/lib/constants"
import { formatPrice, formatPercent } from "@/lib/utils"
import type { PositionWithPnL } from "@/types/portfolio"
import type { MoveAnalysis } from "@/types/agent"

interface Props {
  positions: PositionWithPnL[]
  onEdit: (id: string) => void
  onDelete: (id: string) => void
  onTrade?: (position: PositionWithPnL, action: "add" | "reduce" | "sell") => void
}

export function PositionTable({ positions, onEdit, onDelete, onTrade }: Props) {
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [moveResults, setMoveResults] = useState<Record<string, MoveAnalysis>>({})
  const moveAnalysis = useMoveAnalysis()

  const triggerMoveAnalysis = (pos: PositionWithPnL) => {
    const id = pos.id
    if (expandedId === id) {
      setExpandedId(null)
      return
    }
    setExpandedId(id)
    if (moveResults[id]) return

    const buyDate = pos.buyDate ? new Date(pos.buyDate) : null
    const holdingDays = buyDate ? Math.floor((Date.now() - buyDate.getTime()) / 86400000) : 0

    moveAnalysis.mutate(
      {
        symbol: pos.symbol,
        position: {
          cost_price: pos.costPrice,
          shares: pos.shares,
          holding_days: holdingDays,
        },
      },
      {
        onSuccess: (data) => {
          setMoveResults((prev) => ({ ...prev, [id]: data }))
        },
      },
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-xs text-muted-foreground">
            <th className="py-2 px-3 text-left font-medium">股票</th>
            <th className="py-2 px-3 text-right font-medium">持仓</th>
            <th className="py-2 px-3 text-right font-medium">成本价</th>
            <th className="py-2 px-3 text-right font-medium">现价</th>
            <th className="py-2 px-3 text-right font-medium">市值</th>
            <th className="py-2 px-3 text-right font-medium">盈亏</th>
            <th className="py-2 px-3 text-right font-medium">盈亏%</th>
            <th className="py-2 px-3 text-right font-medium">操作</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((pos) => {
            const pnlColor = pos.pnl > 0
              ? MARKET_COLORS.up
              : pos.pnl < 0
                ? MARKET_COLORS.down
                : MARKET_COLORS.flat
            const isExpanded = expandedId === pos.id

            return (
              <>
                <tr key={pos.id} className="border-b last:border-0 hover:bg-accent/50 transition-colors">
                  <td className="py-2.5 px-3">
                    <Link
                      to={`/stock/${pos.symbol}?from=portfolio`}
                      className="text-left hover:text-primary transition-colors block"
                    >
                      <div className="font-medium">{pos.name}</div>
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs text-muted-foreground font-mono">{pos.symbol}</span>
                        <Badge variant="secondary" className="text-[10px] px-1 py-0">
                          {BOARD_LABELS[pos.board] ?? pos.board}
                        </Badge>
                      </div>
                    </Link>
                  </td>
                  <td className="py-2.5 px-3 text-right font-numeric">{pos.shares}股</td>
                  <td className="py-2.5 px-3 text-right font-numeric">{formatPrice(pos.costPrice)}</td>
                  <td className="py-2.5 px-3 text-right font-numeric">
                    {pos.currentPrice != null ? formatPrice(pos.currentPrice) : "--"}
                  </td>
                  <td className="py-2.5 px-3 text-right font-numeric">
                    ¥{formatPrice(pos.marketValue)}
                  </td>
                  <td className="py-2.5 px-3 text-right font-numeric" style={{ color: pnlColor }}>
                    {pos.pnl >= 0 ? "+" : ""}¥{formatPrice(Math.abs(pos.pnl))}
                  </td>
                  <td className="py-2.5 px-3 text-right font-numeric" style={{ color: pnlColor }}>
                    {formatPercent(pos.pnlPercent)}
                  </td>
                  <td className="py-2.5 px-3 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-market-up hover:text-market-up"
                        title="加仓"
                        onClick={() => onTrade?.(pos, "add")}
                      >
                        <Plus className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-market-down hover:text-market-down"
                        title="减仓"
                        onClick={() => onTrade?.(pos, "reduce")}
                      >
                        <Minus className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-destructive hover:text-destructive"
                        title="清仓"
                        onClick={() => onTrade?.(pos, "sell")}
                      >
                        <LogOut className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        title="涨跌分析"
                        onClick={() => triggerMoveAnalysis(pos)}
                      >
                        <TrendingUp className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        onClick={() => onEdit(pos.id)}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-destructive hover:text-destructive"
                        onClick={() => onDelete(pos.id)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </td>
                </tr>
                {isExpanded && (
                  <tr key={`${pos.id}-move`}>
                    <td colSpan={8} className="bg-accent/20 border-b">
                      <MoveAnalysisPanel
                        data={moveResults[pos.id] ?? null}
                        isLoading={moveAnalysis.isPending && !moveResults[pos.id]}
                        error={!moveResults[pos.id] ? moveAnalysis.error : null}
                        onRefresh={() => {
                          setMoveResults((prev) => {
                            const next = { ...prev }
                            delete next[pos.id]
                            return next
                          })
                          triggerMoveAnalysis(pos)
                        }}
                      />
                    </td>
                  </tr>
                )}
              </>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
