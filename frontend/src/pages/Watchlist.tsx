/** Watchlist — AI-enhanced stock watchlist cards (v36.0). */

import { useNavigate } from "react-router-dom"
import { Loader2, Plus, Eye } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useWatchlistWithAI } from "@/hooks/useMessages"
import type { WatchlistStock } from "@/types/message"
import { cn, formatPercent } from "@/lib/utils"

// ─── Helpers ──────────────────────────────────────────────────────────────────

const AI_ATTITUDE_CONFIG: Record<
  string,
  { label: string; className: string; bgClass: string }
> = {
  bullish: {
    label: "看好",
    className: "text-emerald-500",
    bgClass: "bg-emerald-500/10",
  },
  neutral: {
    label: "中性",
    className: "text-amber-500",
    bgClass: "bg-amber-500/10",
  },
  cautious: {
    label: "谨慎",
    className: "text-red-500",
    bgClass: "bg-red-500/10",
  },
}

function openCommandPalette() {
  document.dispatchEvent(
    new KeyboardEvent("keydown", {
      key: "k",
      metaKey: true,
      bubbles: true,
    }),
  )
}

// ─── StockCard ────────────────────────────────────────────────────────────────

function StockCard({
  stock,
  onClick,
}: {
  stock: WatchlistStock
  onClick: () => void
}) {
  const attitude = AI_ATTITUDE_CONFIG[stock.ai_attitude] ?? AI_ATTITUDE_CONFIG.neutral
  const pctDir =
    stock.pct_change != null
      ? stock.pct_change > 0
        ? "text-market-up"
        : stock.pct_change < 0
          ? "text-market-down"
          : "text-muted-foreground"
      : "text-muted-foreground"

  return (
    <button
      onClick={onClick}
      className="w-full text-left rounded-lg border bg-card p-4 transition-all hover:shadow-md hover:border-primary/20 space-y-3"
    >
      {/* Header: name + code */}
      <div className="flex items-start justify-between">
        <div>
          <div className="font-semibold text-foreground">{stock.name}</div>
          <div className="text-xs text-muted-foreground font-mono">{stock.symbol}</div>
        </div>
        <span
          className={cn(
            "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
            attitude.bgClass,
            attitude.className,
          )}
        >
          {stock.ai_attitude_label || attitude.label}
        </span>
      </div>

      {/* Price + change */}
      <div className="flex items-baseline gap-3">
        <span className="text-xl font-bold text-foreground">
          {stock.price != null ? `\u00A5${stock.price.toFixed(2)}` : "--"}
        </span>
        <span className={cn("text-sm font-medium", pctDir)}>
          {formatPercent(stock.pct_change)}
        </span>
      </div>

      {/* Latest message summary */}
      {stock.latest_message_summary && (
        <p className="text-xs text-muted-foreground line-clamp-2">
          {stock.latest_message_summary}
        </p>
      )}
    </button>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function Watchlist() {
  const navigate = useNavigate()
  const { data: stocks, isLoading, error } = useWatchlistWithAI()

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">自选股</h1>
          <p className="text-sm text-muted-foreground mt-1">
            AI 持续跟踪您关注的股票
          </p>
        </div>
        <Button variant="outline" size="sm" className="gap-1.5" onClick={openCommandPalette}>
          <Plus className="h-3.5 w-3.5" />
          添加
        </Button>
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          加载中...
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
          加载失败: {(error as Error).message}
        </div>
      )}

      {/* Stock grid */}
      {!isLoading && !error && stocks && stocks.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {stocks.map((stock) => (
            <StockCard
              key={stock.symbol}
              stock={stock}
              onClick={() => navigate(`/stock/${stock.symbol}`)}
            />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!isLoading && !error && (!stocks || stocks.length === 0) && (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <Eye className="h-12 w-12 text-muted-foreground/40 mb-4" />
          <p className="text-muted-foreground">还没有关注的股票</p>
          <p className="text-xs text-muted-foreground/60 mt-1">
            点击上方"添加"按钮搜索并添加股票
          </p>
          <Button variant="outline" size="sm" className="mt-4 gap-1.5" onClick={openCommandPalette}>
            <Plus className="h-3.5 w-3.5" />
            添加自选股
          </Button>
        </div>
      )}
    </div>
  )
}
