import { useState, useMemo, useCallback } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { WatchlistTable } from "@/components/stock/WatchlistTable"
import { useWatchlist, useRemoveFromWatchlist } from "@/hooks/useStocks"
import { useRealtimeQuotes } from "@/hooks/useMarket"
import { Star } from "lucide-react"
import { toast } from "sonner"
import type { RealtimeQuote } from "@/types/market"
import type { QuickInsight } from "@/types/agent"
import type { Position } from "@/types/portfolio"

interface WatchlistTabContentProps {
  positions: Position[]
  onSwitchToPositions: () => void
  onAddPosition?: (stock: { symbol: string; name: string; board: string }) => void
}

export function WatchlistTabContent({
  positions,
  onSwitchToPositions,
  onAddPosition,
}: WatchlistTabContentProps) {
  const { data: watchlist = [], isLoading } = useWatchlist()
  const removeMutation = useRemoveFromWatchlist()
  const { data: realtimeData } = useRealtimeQuotes()

  const realtimeMap = useMemo(
    () => new Map<string, RealtimeQuote>(realtimeData?.map((q) => [q.symbol, q]) ?? []),
    [realtimeData],
  )

  // Empty insights map — WatchlistTable requires it but insights are optional
  const insightsMap = useMemo(() => new Map<string, QuickInsight>(), [])

  const positionSymbols = useMemo(
    () => new Set(positions.map((p) => p.symbol)),
    [positions],
  )

  const [removeTarget, setRemoveTarget] = useState<{ symbol: string; name: string } | null>(null)

  const handleRemove = useCallback(
    (symbol: string, name: string) => {
      if (positionSymbols.has(symbol)) {
        toast.info(`${name} 有持仓，请先在持仓中处理`)
        onSwitchToPositions()
        return
      }
      setRemoveTarget({ symbol, name })
    },
    [positionSymbols, onSwitchToPositions],
  )

  const confirmRemove = useCallback(() => {
    if (!removeTarget) return
    removeMutation.mutate(removeTarget.symbol, {
      onSuccess: () => {
        toast.success(`已从自选中移除 ${removeTarget.name}`)
        setRemoveTarget(null)
      },
      onError: () => {
        toast.error("移除失败，请重试")
        setRemoveTarget(null)
      },
    })
  }, [removeTarget, removeMutation])

  if (!isLoading && watchlist.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <Star className="h-10 w-10 text-muted-foreground/30 mx-auto mb-3" />
          <p className="text-muted-foreground text-sm">
            还没有自选股，可在搜索或个股页面中添加
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <>
      <Card>
        <CardHeader className="py-3 px-4">
          <div className="flex items-center gap-2">
            <Star className="h-4 w-4 text-accent-primary" />
            <CardTitle className="text-title">
              自选股 ({watchlist.length})
            </CardTitle>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <WatchlistTable
            stocks={watchlist}
            realtimeMap={realtimeMap}
            insightsMap={insightsMap}
            isLoading={isLoading}
            onRemove={handleRemove}
            onAddPosition={onAddPosition}
          />
        </CardContent>
      </Card>

      <ConfirmDialog
        open={!!removeTarget}
        onOpenChange={(open) => !open && setRemoveTarget(null)}
        title="移除自选"
        description={`确定要从自选中移除 ${removeTarget?.name}(${removeTarget?.symbol}) 吗？`}
        confirmLabel="移除"
        variant="destructive"
        onConfirm={confirmRemove}
        loading={removeMutation.isPending}
      />
    </>
  )
}
