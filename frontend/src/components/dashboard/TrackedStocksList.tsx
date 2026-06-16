import { useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { useWatchlist } from "@/hooks/useStocks"
import { usePortfolio, computePortfolioSummary } from "@/hooks/usePortfolio"
import { useRealtimeQuotes } from "@/hooks/useMarket"
import { formatPercent } from "@/lib/utils"
import { formatPnL } from "@/lib/formatters"
import { TrendingUp, Briefcase, Star, Search } from "lucide-react"
import type { RealtimeQuote } from "@/types/market"
import type { Position } from "@/types/portfolio"

type FilterMode = "all" | "held" | "watch"

interface TrackedStock {
  symbol: string
  name: string
  board: string
  quote: RealtimeQuote | null
  position: Position | null
}

interface TrackedStocksListProps {
  /** Pre-select a filter (e.g. Portfolio page uses "held") */
  filter?: FilterMode
  /** Compact mode hides summary bar */
  compact?: boolean
}

export function TrackedStocksList({ filter: initialFilter, compact = false }: TrackedStocksListProps) {
  const [activeFilter, setActiveFilter] = useState<FilterMode>(initialFilter ?? "all")
  const { data: watchlist, isLoading: watchlistLoading } = useWatchlist()
  const { positions, isEmpty: portfolioEmpty } = usePortfolio()
  const { data: realtimeData } = useRealtimeQuotes()

  const realtimeMap = useMemo(
    () => new Map<string, RealtimeQuote>(realtimeData?.map((q) => [q.symbol, q]) ?? []),
    [realtimeData],
  )

  const positionMap = useMemo(
    () => new Map<string, Position>(positions.map((p) => [p.symbol, p])),
    [positions],
  )

  // Merge watchlist + portfolio into unified list
  const trackedStocks = useMemo<TrackedStock[]>(() => {
    if (!watchlist) return []
    const result: TrackedStock[] = watchlist.map((w) => ({
      symbol: w.symbol,
      name: w.name,
      board: w.board,
      quote: realtimeMap.get(w.symbol) ?? null,
      position: positionMap.get(w.symbol) ?? null,
    }))
    return result
  }, [watchlist, realtimeMap, positionMap])

  // Filter
  const filtered = useMemo(() => {
    switch (activeFilter) {
      case "held":
        return trackedStocks.filter((s) => s.position !== null)
      case "watch":
        return trackedStocks.filter((s) => s.position === null)
      default:
        return trackedStocks
    }
  }, [trackedStocks, activeFilter])

  // Portfolio summary for header
  const portfolioSummary = useMemo(
    () => portfolioEmpty ? null : computePortfolioSummary(positions, realtimeMap),
    [positions, portfolioEmpty, realtimeMap],
  )

  const heldCount = trackedStocks.filter((s) => s.position !== null).length
  const watchCount = trackedStocks.filter((s) => s.position === null).length

  if (watchlistLoading) {
    return (
      <Card>
        <CardContent className="p-5 space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full rounded-md" />
          ))}
        </CardContent>
      </Card>
    )
  }

  if (!watchlist || trackedStocks.length === 0) {
    return (
      <Card className="border-dashed">
        <CardContent className="flex flex-col items-center justify-center py-14 text-muted-foreground">
          <div className="rounded-full bg-muted p-4 mb-4">
            <Search className="h-8 w-8" />
          </div>
          <p className="text-title text-foreground">搜索并添加股票</p>
          <p className="text-caption mt-1.5">使用搜索框查找股票，或按 ⌘K 全局搜索</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader className="py-3 px-5 flex-row items-center justify-between space-y-0">
        <CardTitle className="text-title flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-primary" />
          我的股票
        </CardTitle>
        {!compact && portfolioSummary && (
          <div className="flex items-center gap-2 text-xs">
            <span className="text-muted-foreground">总盈亏</span>
            <span className={`font-numeric font-semibold ${portfolioSummary.totalPnL > 0 ? "text-market-up" : portfolioSummary.totalPnL < 0 ? "text-market-down" : ""}`}>
              {formatPnL(portfolioSummary.totalPnL)}
            </span>
            <span className={`font-numeric ${portfolioSummary.totalPnLPercent > 0 ? "text-market-up" : portfolioSummary.totalPnLPercent < 0 ? "text-market-down" : ""}`}>
              ({formatPercent(portfolioSummary.totalPnLPercent)})
            </span>
          </div>
        )}
      </CardHeader>

      {/* Filter chips */}
      {!initialFilter && (
        <div className="flex items-center gap-2 px-5 pb-3">
          <FilterChip
            label="全部"
            count={trackedStocks.length}
            active={activeFilter === "all"}
            onClick={() => setActiveFilter("all")}
          />
          <FilterChip
            label="持仓"
            count={heldCount}
            icon={<Briefcase className="h-3 w-3" />}
            active={activeFilter === "held"}
            onClick={() => setActiveFilter("held")}
          />
          <FilterChip
            label="关注"
            count={watchCount}
            icon={<Star className="h-3 w-3" />}
            active={activeFilter === "watch"}
            onClick={() => setActiveFilter("watch")}
          />
        </div>
      )}

      {/* Stock list */}
      <CardContent className="p-0">
        <div className="divide-y divide-border-subtle">
          {filtered.map((stock) => (
            <StockRow key={stock.symbol} stock={stock} />
          ))}
        </div>
        {filtered.length === 0 && (
          <div className="py-8 text-center text-xs text-muted-foreground">
            {activeFilter === "held" ? "暂无持仓股票" : "暂无关注股票"}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function FilterChip({
  label,
  count,
  icon,
  active,
  onClick,
}: {
  label: string
  count: number
  icon?: React.ReactNode
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      className={`flex items-center gap-1 rounded-md px-2.5 py-1 text-xs transition-colors ${
        active
          ? "bg-primary/10 text-primary font-medium"
          : "text-muted-foreground hover:bg-muted/50"
      }`}
      onClick={onClick}
    >
      {icon}
      {label}
      <span className="font-numeric ml-0.5">{count}</span>
    </button>
  )
}

function StockRow({ stock }: { stock: TrackedStock }) {
  const { symbol, name, quote, position } = stock
  const pctChange = quote?.pct_change ?? null
  const price = quote?.price ?? null

  // Position P&L
  let positionPnlPct: number | null = null
  if (position && price) {
    positionPnlPct = ((price - position.costPrice) / position.costPrice) * 100
  }

  return (
    <Link
      to={`/stock/${symbol}`}
      className="flex items-center gap-3 px-5 py-3 hover:bg-bg-hover transition-colors"
    >
      {/* Icon: held or watched */}
      <span className="w-4 shrink-0 text-center">
        {position ? (
          <Briefcase className="h-3.5 w-3.5 text-primary" />
        ) : (
          <Star className="h-3.5 w-3.5 text-muted-foreground" />
        )}
      </span>

      {/* Name + symbol */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium truncate">{name}</span>
          <span className="text-xs text-muted-foreground font-numeric">{symbol}</span>
        </div>
      </div>

      {/* Price */}
      <div className="text-right shrink-0">
        {price != null ? (
          <span className="text-sm font-numeric">
            ¥{price.toFixed(2)}
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">--</span>
        )}
      </div>

      {/* Today change */}
      <div className="w-16 text-right shrink-0">
        {pctChange != null ? (
          <span className={`text-xs font-numeric ${pctChange > 0 ? "text-market-up" : pctChange < 0 ? "text-market-down" : "text-muted-foreground"}`}>
            {formatPercent(pctChange)}
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">--</span>
        )}
      </div>

      {/* Position P&L (only for held stocks) */}
      <div className="w-16 text-right shrink-0">
        {positionPnlPct != null ? (
          <Badge
            variant={positionPnlPct > 0 ? "up" : positionPnlPct < 0 ? "down" : "secondary"}
            className="text-[10px] font-numeric"
          >
            {positionPnlPct > 0 ? "+" : ""}{positionPnlPct.toFixed(1)}%
          </Badge>
        ) : position ? (
          <span className="text-xs text-muted-foreground">--</span>
        ) : null}
      </div>
    </Link>
  )
}
