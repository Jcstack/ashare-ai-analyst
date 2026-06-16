import { useMemo, useState, useCallback, useEffect, useRef } from "react"
import { useNavigate } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { ArrowUpDown, Sparkles, MoreHorizontal, Eye, Briefcase, Trash2 } from "lucide-react"
import { formatPrice, formatPercent, formatVolume, getPriceDirection, cn } from "@/lib/utils"
import { MARKET_COLORS, BOARD_LABELS, AI_SIGNAL_LABELS } from "@/lib/constants"
import type { WatchlistItem } from "@/types/stock"
import type { RealtimeQuote } from "@/types/market"
import type { QuickInsight } from "@/types/agent"

type SortField = "name" | "price" | "pct_change" | "volume" | "signal"
type SortDir = "asc" | "desc"

interface WatchlistTableProps {
  stocks: WatchlistItem[]
  realtimeMap: Map<string, RealtimeQuote>
  insightsMap: Map<string, QuickInsight>
  isLoading?: boolean
  onRemove?: (symbol: string, name: string) => void
  onAddPosition?: (stock: { symbol: string; name: string; board: string }) => void
}

function SignalBadge({ insight }: { insight?: QuickInsight }) {
  if (!insight) return <span className="text-xs text-muted-foreground">--</span>

  const colorMap: Record<string, string> = {
    bullish: "text-market-up bg-market-up/10 border-market-up/20",
    bearish: "text-market-down bg-market-down/10 border-market-down/20",
    neutral: "text-muted-foreground bg-muted/50 border-muted",
  }

  return (
    <Badge variant="outline" className={cn("text-xs px-1.5 py-0 gap-1", colorMap[insight.signal] || colorMap.neutral)}>
      <Sparkles className="h-3 w-3" />
      {AI_SIGNAL_LABELS[insight.signal] || insight.signal}
      <span className="opacity-70">{Math.round(insight.confidence * 100)}%</span>
    </Badge>
  )
}

export function WatchlistTable({ stocks, realtimeMap, insightsMap, isLoading, onRemove, onAddPosition }: WatchlistTableProps) {
  const navigate = useNavigate()
  const [sortField, setSortField] = useState<SortField>("pct_change")
  const [sortDir, setSortDir] = useState<SortDir>("desc")
  const prevPricesRef = useRef<Map<string, number>>(new Map())
  const [flashMap, setFlashMap] = useState<Map<string, "up" | "down">>(new Map())

  // Detect price changes for flash animation
  useEffect(() => {
    const newFlash = new Map<string, "up" | "down">()
    for (const [sym, quote] of realtimeMap) {
      const prev = prevPricesRef.current.get(sym)
      if (prev != null && quote.price != null && quote.price !== prev) {
        newFlash.set(sym, quote.price > prev ? "up" : "down")
      }
      if (quote.price != null) {
        prevPricesRef.current.set(sym, quote.price)
      }
    }
    if (newFlash.size > 0) {
      setFlashMap(newFlash)
      const timer = setTimeout(() => setFlashMap(new Map()), 800)
      return () => clearTimeout(timer)
    }
  }, [realtimeMap])

  const toggleSort = useCallback((field: SortField) => {
    if (sortField === field) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortField(field)
      setSortDir("desc")
    }
  }, [sortField])

  const merged = useMemo(() => {
    return stocks.map((s) => {
      const rt = realtimeMap.get(s.symbol)
      return {
        ...s,
        price: rt?.price ?? s.close,
        change: rt?.change ?? s.change,
        pct_change: rt?.pct_change ?? s.pct_change,
        volume: rt?.volume ?? s.volume,
        open: rt?.open ?? s.open,
        high: rt?.high ?? s.high,
        low: rt?.low ?? s.low,
      }
    })
  }, [stocks, realtimeMap])

  const sorted = useMemo(() => {
    return [...merged].sort((a, b) => {
      let cmp = 0
      switch (sortField) {
        case "name": cmp = a.name.localeCompare(b.name); break
        case "price": cmp = (a.price ?? 0) - (b.price ?? 0); break
        case "pct_change": cmp = (a.pct_change ?? 0) - (b.pct_change ?? 0); break
        case "volume": cmp = (a.volume ?? 0) - (b.volume ?? 0); break
        case "signal": {
          const aConf = insightsMap.get(a.symbol)?.confidence ?? 0
          const bConf = insightsMap.get(b.symbol)?.confidence ?? 0
          cmp = aConf - bConf
          break
        }
      }
      return sortDir === "asc" ? cmp : -cmp
    })
  }, [merged, sortField, sortDir, insightsMap])

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    )
  }

  const SortHeader = ({ field, label }: { field: SortField; label: string }) => (
    <th
      className="px-2 py-2 text-left text-xs font-medium text-muted-foreground cursor-pointer select-none hover:text-foreground transition-colors"
      onClick={() => toggleSort(field)}
    >
      <span className="flex items-center gap-1">
        {label}
        <ArrowUpDown className={cn("h-3 w-3", sortField === field ? "text-foreground" : "opacity-30")} />
      </span>
    </th>
  )

  return (
    <div className="overflow-hidden">
      <table className="w-full data-table">
        <thead>
          <tr className="bg-muted/30">
            <SortHeader field="name" label="股票" />
            <SortHeader field="price" label="最新价" />
            <SortHeader field="pct_change" label="涨跌幅" />
            <th className="px-2 py-2 text-left text-xs font-medium text-muted-foreground">今开/最高/最低</th>
            <SortHeader field="volume" label="成交量" />
            <SortHeader field="signal" label="AI信号" />
            {(onRemove || onAddPosition) && (
              <th className="px-2 py-2 text-right text-xs font-medium text-muted-foreground w-12">操作</th>
            )}
          </tr>
        </thead>
        <tbody>
          {sorted.map((stock) => {
            const dir = getPriceDirection(stock.change)
            const color = dir === "up" ? MARKET_COLORS.up : dir === "down" ? MARKET_COLORS.down : MARKET_COLORS.flat
            const flash = flashMap.get(stock.symbol)
            const insight = insightsMap.get(stock.symbol)

            return (
              <tr
                key={stock.symbol}
                className={cn(
                  "data-row-hover cursor-pointer transition-colors",
                  flash === "up" && "flash-up",
                  flash === "down" && "flash-down",
                )}
                onClick={() => navigate(`/stock/${stock.symbol}`)}
              >
                <td className="px-2 py-1.5">
                  <div className="flex items-center gap-2">
                    <div>
                      <div className="text-sm font-medium">{stock.name}</div>
                      <div className="text-xs text-muted-foreground flex items-center gap-1">
                        {stock.symbol}
                        <Badge variant="outline" className="text-[10px] px-1 py-0">
                          {BOARD_LABELS[stock.board] || stock.board}
                        </Badge>
                      </div>
                    </div>
                  </div>
                </td>
                <td className="px-2 py-1.5 col-numeric">
                  <span className="font-numeric text-sm font-semibold" style={{ color }}>
                    {stock.price != null ? formatPrice(stock.price) : "--"}
                  </span>
                </td>
                <td className="px-2 py-1.5 col-numeric">
                  <div className="font-numeric text-sm" style={{ color }}>
                    <div className="font-medium">{stock.pct_change != null ? formatPercent(stock.pct_change) : "--"}</div>
                    <div className="text-xs opacity-70">{stock.change != null ? (stock.change > 0 ? "+" : "") + stock.change.toFixed(2) : ""}</div>
                  </div>
                </td>
                <td className="px-2 py-1.5">
                  <div className="font-numeric text-xs text-muted-foreground space-y-0.5">
                    <div>开 {stock.open != null ? formatPrice(stock.open) : "--"}</div>
                    <div>高 <span style={{ color: MARKET_COLORS.up }}>{stock.high != null ? formatPrice(stock.high) : "--"}</span></div>
                    <div>低 <span style={{ color: MARKET_COLORS.down }}>{stock.low != null ? formatPrice(stock.low) : "--"}</span></div>
                  </div>
                </td>
                <td className="px-2 py-1.5 col-numeric">
                  <span className="font-numeric text-xs">
                    {stock.volume != null ? formatVolume(stock.volume) : "--"}
                  </span>
                </td>
                <td className="px-2 py-1.5">
                  <SignalBadge insight={insight} />
                </td>
                {(onRemove || onAddPosition) && (
                  <td className="px-2 py-1.5 text-right">
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <MoreHorizontal className="h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
                        <DropdownMenuItem onClick={() => navigate(`/stock/${stock.symbol}`)}>
                          <Eye className="h-4 w-4" />
                          查看详情
                        </DropdownMenuItem>
                        {onAddPosition && (
                          <DropdownMenuItem onClick={() => onAddPosition({ symbol: stock.symbol, name: stock.name, board: stock.board })}>
                            <Briefcase className="h-4 w-4" />
                            添加持仓
                          </DropdownMenuItem>
                        )}
                        {onRemove && (
                          <>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem variant="destructive" onClick={() => onRemove(stock.symbol, stock.name)}>
                              <Trash2 className="h-4 w-4" />
                              移除自选
                            </DropdownMenuItem>
                          </>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </td>
                )}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
