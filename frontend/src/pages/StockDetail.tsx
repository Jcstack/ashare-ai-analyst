import { useMemo, useState, useCallback } from "react"
import { Link, useParams, useSearchParams } from "react-router-dom"
import { Star, StarOff, Briefcase, BrainCircuit } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Breadcrumb, BreadcrumbItem, BreadcrumbLink, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { useStockDetail, useAddToWatchlist, useRemoveFromWatchlist, useWatchlist } from "@/hooks/useStocks"
import { useRealtimeQuotes } from "@/hooks/useMarket"
import { usePortfolio } from "@/hooks/usePortfolio"
import { AddPositionDialog } from "@/components/portfolio/AddPositionDialog"
import { PositionContextCard } from "@/components/stock/PositionContextCard"
import { RealtimePriceHeader } from "@/components/stock/RealtimePriceHeader"
import { useChatStore } from "@/stores/chatStore"
import { toast } from "sonner"
import type { RealtimeQuote } from "@/types/market"
import type { Position } from "@/types/portfolio"

export default function StockDetail() {
  const { symbol = "" } = useParams<{ symbol: string }>()
  const [searchParams] = useSearchParams()
  const fromPortfolio = searchParams.get("from") === "portfolio"
  const { data: stock, isLoading: loadingStock } = useStockDetail(symbol)
  const { data: realtimeData } = useRealtimeQuotes(symbol ? [symbol] : undefined)
  const { data: watchlist = [] } = useWatchlist()
  const { positions, addPosition } = usePortfolio()
  const addWatchlistMutation = useAddToWatchlist()
  const removeWatchlistMutation = useRemoveFromWatchlist()
  const openChatWithContext = useChatStore((s) => s.openChatWithContext)
  const [positionDialogOpen, setPositionDialogOpen] = useState(false)

  const isInWatchlist = watchlist.some((w) => w.symbol === symbol)
  const currentPosition = positions.find((p) => p.symbol === symbol) ?? null
  const isInPortfolio = currentPosition !== null

  const realtimeQuote = useMemo<RealtimeQuote | null>(() => {
    if (!realtimeData) return null
    return realtimeData.find((q) => q.symbol === symbol) ?? null
  }, [realtimeData, symbol])

  const preselectedStock = useMemo(
    () => stock ? { symbol: stock.symbol, name: stock.name, board: stock.board } : null,
    [stock?.symbol, stock?.name, stock?.board],
  )

  const handlePositionSubmit = useCallback((pos: Omit<Position, "id">) => {
    addPosition(pos)
    const alreadyInWatchlist = watchlist.some((w) => w.symbol === pos.symbol)
    if (!alreadyInWatchlist) {
      addWatchlistMutation.mutate(
        { symbol: pos.symbol, name: pos.name, board: pos.board },
        {
          onSuccess: () => toast.success(`已添加持仓 ${pos.name}，已同步加入自选`),
          onError: () => toast.success(`已添加持仓 ${pos.name}`),
        },
      )
    } else {
      toast.success(`已添加持仓 ${pos.name}`)
    }
  }, [addPosition, watchlist, addWatchlistMutation])

  if (loadingStock) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-5 w-48" />
        <div className="space-y-2">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-10 w-40" />
        </div>
      </div>
    )
  }

  if (!stock) {
    return (
      <div className="text-center py-20 text-muted-foreground">
        未找到股票 {symbol}
      </div>
    )
  }

  return (
    <div className="space-y-5">
      {/* Breadcrumb + Actions */}
      <div className="flex items-center justify-between">
        <Breadcrumb>
          <BreadcrumbList>
            <BreadcrumbItem>
              <BreadcrumbLink asChild>
                <Link to={fromPortfolio ? "/portfolio" : "/"}>{fromPortfolio ? "持仓" : "消息中心"}</Link>
              </BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbPage>{stock.name}</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>
        <div className="flex items-center gap-2">
          {isInWatchlist ? (
            <Button
              variant="outline"
              size="sm"
              className="gap-1.5"
              onClick={() => {
                removeWatchlistMutation.mutate(symbol, {
                  onSuccess: () => toast.success(`已取消自选 ${stock.name}`),
                  onError: () => toast.error("操作失败，请重试"),
                })
              }}
              disabled={removeWatchlistMutation.isPending}
            >
              <StarOff className="h-4 w-4" />
              取消自选
            </Button>
          ) : (
            <Button
              variant="outline"
              size="sm"
              className="gap-1.5"
              onClick={() => {
                addWatchlistMutation.mutate(
                  { symbol, name: stock.name, board: stock.board },
                  {
                    onSuccess: () => toast.success(`已添加 ${stock.name} 到自选`),
                    onError: () => toast.error("操作失败，请重试"),
                  },
                )
              }}
              disabled={addWatchlistMutation.isPending}
            >
              <Star className="h-4 w-4" />
              加自选
            </Button>
          )}
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            onClick={() => setPositionDialogOpen(true)}
          >
            <Briefcase className="h-4 w-4" />
            {isInPortfolio ? "追加持仓" : "添加持仓"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            onClick={() => openChatWithContext(
              { symbol, mode: "stock" },
              `帮我分析一下 ${stock.name}(${symbol})`
            )}
          >
            <BrainCircuit className="h-4 w-4" />
            咨询 Agent
          </Button>
        </div>
      </div>

      {/* Price Header */}
      <div className="rounded-md border p-5">
        <RealtimePriceHeader stock={stock} realtimeQuote={realtimeQuote} />
      </div>

      {/* Position Context — when stock is held */}
      {currentPosition && (
        <PositionContextCard position={currentPosition} quote={realtimeQuote} />
      )}

      {/* Position Dialog */}
      <AddPositionDialog
        open={positionDialogOpen}
        onOpenChange={setPositionDialogOpen}
        onSubmit={handlePositionSubmit}
        preselectedStock={preselectedStock}
      />
    </div>
  )
}
