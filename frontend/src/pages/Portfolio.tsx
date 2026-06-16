import { useState, useMemo, useCallback } from "react"
import { Plus, Sparkles, TrendingUp, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { usePortfolio, computePortfolioSummary } from "@/hooks/usePortfolio"
import { usePortfolioDiagnosis } from "@/hooks/usePortfolioDiagnosis"
import { useRealtimeQuotes } from "@/hooks/useMarket"
import { useAddToWatchlist, useWatchlist } from "@/hooks/useStocks"
import { CapitalOverview } from "@/components/portfolio/CapitalOverview"
import { PortfolioSummaryCards } from "@/components/portfolio/PortfolioSummaryCards"
import { PositionTable } from "@/components/portfolio/PositionTable"
import { AddPositionDialog } from "@/components/portfolio/AddPositionDialog"
import { DiagnosisPanel } from "@/components/portfolio/DiagnosisPanel"
import { PortfolioOnboarding } from "@/components/portfolio/PortfolioOnboarding"
import { StrategyInsightBadge } from "@/components/portfolio/StrategyInsightBadge"
import { TradeHistoryPanel } from "@/components/portfolio/TradeHistoryPanel"
import { WatchlistTabContent } from "@/components/portfolio/WatchlistTabContent"
import { TradeDialog } from "@/components/trade/TradeDialog"
import type { TradeContext } from "@/components/trade/TradeDialog"
import { useMarketStatus } from "@/hooks/useMarketStatus"
import { toast } from "sonner"
import type { RealtimeQuote } from "@/types/market"
import type { Position, PositionWithPnL } from "@/types/portfolio"

export default function Portfolio() {
  const { positions, isEmpty, isLoading, addPosition, updatePosition, liquidatePosition } =
    usePortfolio()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingPosition, setEditingPosition] = useState<Position | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Position | null>(null)
  const [liquidating, setLiquidating] = useState(false)
  const [capitalVersion, setCapitalVersion] = useState(0)
  const [activeTab, setActiveTab] = useState("positions")
  const [tradeDialogOpen, setTradeDialogOpen] = useState(false)
  const [tradeContext, setTradeContext] = useState<TradeContext | null>(null)
  const { data: watchlist = [] } = useWatchlist()
  const addWatchlistMutation = useAddToWatchlist()
  const { data: marketStatus } = useMarketStatus()

  const { data: realtimeData } = useRealtimeQuotes()

  const realtimeMap = useMemo(
    () => new Map<string, RealtimeQuote>(realtimeData?.map((q) => [q.symbol, q]) ?? []),
    [realtimeData],
  )

  const summary = useMemo(
    () => computePortfolioSummary(positions, realtimeMap),
    [positions, realtimeMap],
  )

  const diagnosis = usePortfolioDiagnosis()

  // Show tabs when there are positions OR watchlist items
  const showTabs = !isEmpty || watchlist.length > 0

  const handleAdd = () => {
    setEditingPosition(null)
    setDialogOpen(true)
  }

  const handleEdit = (id: string) => {
    const pos = positions.find((p) => p.id === id)
    if (pos) {
      setEditingPosition(pos)
      setDialogOpen(true)
    }
  }

  const handleDelete = (id: string) => {
    const pos = positions.find((p) => p.id === id)
    if (pos) {
      setDeleteTarget(pos)
    }
  }

  const handleTrade = useCallback(
    (pos: PositionWithPnL, action: "add" | "reduce" | "sell") => {
      const rt = realtimeMap.get(pos.symbol)
      setTradeContext({
        action,
        symbol: pos.symbol,
        stockName: pos.name,
        maxShares: pos.shares,
        defaultPrice: rt?.price ?? pos.costPrice,
      })
      setTradeDialogOpen(true)
    },
    [realtimeMap],
  )

  const getDeletePrice = useCallback(
    (pos: Position) => {
      const rt = realtimeMap.get(pos.symbol)
      return rt?.price ?? pos.costPrice
    },
    [realtimeMap],
  )

  const confirmDelete = useCallback(async () => {
    if (!deleteTarget || liquidating) return
    const currentPrice = getDeletePrice(deleteTarget)
    setLiquidating(true)
    try {
      await liquidatePosition(deleteTarget, currentPrice)
      toast.success(`已清仓 ${deleteTarget.name}，¥${(deleteTarget.shares * currentPrice).toLocaleString()} 已返还`)
      setDeleteTarget(null)
      setCapitalVersion((v) => v + 1)
    } catch {
      toast.error("清仓失败，请重试")
    } finally {
      setLiquidating(false)
    }
  }, [deleteTarget, liquidating, getDeletePrice, liquidatePosition])

  const handleDialogSubmit = async (pos: Omit<Position, "id">) => {
    if (editingPosition) {
      updatePosition(editingPosition.id, pos)
      toast.success(`已更新 ${pos.name}`)
    } else {
      await addPosition(pos)
      const isInWatchlist = watchlist.some((w) => w.symbol === pos.symbol)
      if (!isInWatchlist) {
        addWatchlistMutation.mutate(
          { symbol: pos.symbol, name: pos.name, board: pos.board },
          {
            onSuccess: () => {
              toast.success(`已添加持仓 ${pos.name}，已同步加入自选`)
            },
            onError: () => {
              toast.success(`已添加持仓 ${pos.name}`)
            },
          },
        )
      } else {
        toast.success(`已添加持仓 ${pos.name}`)
      }
    }
  }

  const handleDiagnose = () => {
    if (summary.positions.length === 0) return
    diagnosis.mutate(summary.positions)
  }

  const handleAddPositionFromWatchlist = useCallback(
    (_stock: { symbol: string; name: string; board: string }) => {
      setEditingPosition(null)
      setDialogOpen(true)
    },
    [],
  )

  // Build the delete confirmation description with capital recovery info
  const deleteDescription = useMemo(() => {
    if (!deleteTarget) return ""
    const price = getDeletePrice(deleteTarget)
    const totalValue = deleteTarget.shares * price
    const isMarketClosed = marketStatus && !marketStatus.is_trading
    return (
      <div className="space-y-2 text-sm">
        {isMarketClosed && (
          <div className="rounded-md bg-yellow-500/10 border border-yellow-500/20 px-3 py-2 text-xs text-yellow-700 dark:text-yellow-400">
            当前非交易时段，清仓操作将以最近收盘价计算
          </div>
        )}
        <p className="text-muted-foreground">
          {deleteTarget.symbol} · {deleteTarget.shares}股 × ¥{price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </p>
        <p className="font-medium text-foreground">
          ¥{totalValue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} 将返还至可用现金
        </p>
        <p className="text-muted-foreground text-xs">此操作无法撤销。自选股中该股票将保留。</p>
      </div>
    )
  }, [deleteTarget, getDeletePrice, marketStatus])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        <span className="ml-2 text-muted-foreground">加载持仓数据...</span>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-headline">投资管理</h1>
          <p className="text-caption text-muted-foreground mt-0.5">持仓、自选与AI诊断</p>
        </div>
        {!isEmpty && activeTab === "positions" && (
          <div className="flex items-center gap-2">
            <Button variant="outline" className="gap-2" onClick={handleAdd}>
              <Plus className="h-4 w-4" />
              添加持仓
            </Button>
            <Button
              className="gap-2"
              onClick={handleDiagnose}
              disabled={diagnosis.isPending}
            >
              <Sparkles className="h-4 w-4" />
              {diagnosis.isPending ? "诊断中..." : "AI 持仓诊断"}
            </Button>
          </div>
        )}
      </div>

      {/* Capital Overview — always shown */}
      <CapitalOverview
        key={capitalVersion}
        realtimePositionValue={summary.totalMarketValue || undefined}
      />

      {!showTabs ? (
        <PortfolioOnboarding onAddClick={handleAdd} />
      ) : (
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList>
            <TabsTrigger value="positions">持仓</TabsTrigger>
            <TabsTrigger value="watchlist">自选股</TabsTrigger>
            <TabsTrigger value="trades">交易记录</TabsTrigger>
          </TabsList>

          <TabsContent value="positions" className="space-y-5 mt-4">
            {isEmpty ? (
              <PortfolioOnboarding onAddClick={handleAdd} />
            ) : (
              <>
                {/* Summary Cards */}
                <PortfolioSummaryCards summary={summary} />

                {/* AI Diagnosis */}
                {(diagnosis.data || diagnosis.isPending || diagnosis.error) && (
                  <DiagnosisPanel
                    diagnosis={diagnosis.data ?? null}
                    isLoading={diagnosis.isPending}
                    error={diagnosis.error}
                    onRetry={handleDiagnose}
                  />
                )}

                {/* Strategy Insights */}
                {positions.length > 0 && (
                  <Card>
                    <CardHeader className="py-3 px-4">
                      <div className="flex items-center gap-2">
                        <TrendingUp className="h-4 w-4 text-accent-primary" />
                        <CardTitle className="text-title">策略信号</CardTitle>
                      </div>
                    </CardHeader>
                    <CardContent className="px-4 pb-3">
                      <div className="flex flex-wrap gap-2">
                        {positions.map((p) => (
                          <div key={p.id} className="flex items-center gap-1.5 text-sm">
                            <span className="text-muted-foreground">{p.name}</span>
                            <StrategyInsightBadge symbol={p.symbol} />
                          </div>
                        ))}
                      </div>
                    </CardContent>
                  </Card>
                )}

                {/* Position Table */}
                <Card>
                  <CardHeader className="py-3 px-4">
                    <CardTitle className="text-title">持仓明细</CardTitle>
                  </CardHeader>
                  <CardContent className="p-0">
                    <PositionTable
                      positions={summary.positions}
                      onEdit={handleEdit}
                      onDelete={handleDelete}
                      onTrade={handleTrade}
                    />
                  </CardContent>
                </Card>
              </>
            )}
          </TabsContent>

          <TabsContent value="watchlist" className="mt-4">
            <WatchlistTabContent
              positions={positions}
              onSwitchToPositions={() => setActiveTab("positions")}
              onAddPosition={handleAddPositionFromWatchlist}
            />
          </TabsContent>

          <TabsContent value="trades" className="mt-4">
            <TradeHistoryPanel />
          </TabsContent>
        </Tabs>
      )}

      {/* Disclaimer */}
      <div className="rounded-lg border border-dashed p-3">
        <p className="text-xs text-muted-foreground leading-relaxed">
          <strong>免责声明：</strong>本系统仅供研究学习使用，不构成任何投资建议。股市有风险，投资需谨慎。所有分析结论与预测信号均基于历史数据和模型推理，不保证未来收益。用户据此进行的任何投资操作，风险自担。
        </p>
      </div>

      {/* Add/Edit Dialog */}
      <AddPositionDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onSubmit={handleDialogSubmit}
        editPosition={editingPosition}
      />

      {/* Delete Confirmation — enhanced with capital recovery info */}
      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title={`清仓 — ${deleteTarget?.name ?? ""}`}
        description={deleteDescription}
        confirmLabel={liquidating ? "处理中..." : "确认清仓"}
        variant="destructive"
        onConfirm={confirmDelete}
        loading={liquidating}
      />

      {/* Trade Dialog (add/reduce/sell) */}
      <TradeDialog
        open={tradeDialogOpen}
        onOpenChange={setTradeDialogOpen}
        tradeContext={tradeContext}
      />
    </div>
  )
}
