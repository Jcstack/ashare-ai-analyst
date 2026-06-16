import { useEffect, useMemo, useRef, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useWatchlist, useRemoveFromWatchlist, useAddToWatchlist } from "@/hooks/useStocks"
import { useRealtimeQuotes, useTradingCalendar } from "@/hooks/useMarket"
import { usePortfolio, computePortfolioSummary } from "@/hooks/usePortfolio"
import StockSearch from "@/components/stock/StockSearch"
import { SmartAlerts } from "@/components/stock/SmartAlerts"
import { AgentBriefingCard } from "@/components/dashboard/AgentBriefingCard"
import { CapitalFlowGauge } from "@/components/dashboard/CapitalFlowGauge"
import { TrackedStocksList } from "@/components/dashboard/TrackedStocksList"
import { AddPositionDialog } from "@/components/portfolio/AddPositionDialog"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { useMarketPulse } from "@/hooks/useSentiment"
import { useUnreadCount } from "@/hooks/useNotifications"
import { CalendarOff, Loader2, Radio, Bell, ArrowRight, ChevronDown } from "lucide-react"
import { formatPercent } from "@/lib/utils"
import { toast } from "sonner"
import type { StockSearchItem } from "@/types/search"
import type { RealtimeQuote } from "@/types/market"
import { Button } from "@/components/ui/button"
import { useReopenBriefing } from "@/hooks/useAdvisor"
import { HotStockRecommend } from "@/components/stock/HotStockRecommend"
import { PhaseIndicator } from "@/components/intelligence/PhaseIndicator"

function SummaryBar({ stocks, realtimeMap }: { stocks: { symbol: string; name: string; pct_change: number | null }[]; realtimeMap: Map<string, RealtimeQuote> }) {
  const stats = useMemo(() => {
    const merged = stocks.map((s) => {
      const rt = realtimeMap.get(s.symbol)
      return { ...s, pct_change: rt?.pct_change ?? s.pct_change }
    })
    const withPct = merged.filter((s) => s.pct_change != null)
    const up = withPct.filter((s) => (s.pct_change ?? 0) > 0).length
    const down = withPct.filter((s) => (s.pct_change ?? 0) < 0).length
    const flat = withPct.length - up - down
    const avgPct = withPct.length > 0
      ? withPct.reduce((sum, s) => sum + (s.pct_change ?? 0), 0) / withPct.length
      : null
    return { up, down, flat, total: stocks.length, avgPct }
  }, [stocks, realtimeMap])

  return (
    <div className="flex items-center gap-4 text-caption">
      <span className="text-muted-foreground">自选 <strong className="text-foreground">{stats.total}</strong></span>
      <span className="text-market-up">涨 {stats.up}</span>
      <span className="text-market-down">跌 {stats.down}</span>
      <span className="text-muted-foreground">平 {stats.flat}</span>
      {stats.avgPct != null && (
        <span className="font-numeric">
          均幅 <span className={stats.avgPct > 0 ? "text-market-up" : stats.avgPct < 0 ? "text-market-down" : "text-market-flat"}>
            {formatPercent(stats.avgPct)}
          </span>
        </span>
      )}
    </div>
  )
}

function useClock() {
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])
  return now
}

export default function Dashboard() {
  const clock = useClock()
  const { data: stocks, isLoading, error } = useWatchlist()
  const { data: realtimeData, isFetching: realtimeFetching } = useRealtimeQuotes()
  const { positions: portfolioPositions, isEmpty: portfolioEmpty, addPosition } = usePortfolio()
  const removeMutation = useRemoveFromWatchlist()
  const addWatchlistMutation = useAddToWatchlist()
  const navigate = useNavigate()
  const { data: calendarInfo } = useTradingCalendar()
  const isHolidayPeriod = calendarInfo?.is_holiday_period ?? false
  const [briefingRequested, setBriefingRequested] = useState(false)
  const { data: briefingData, isLoading: briefingLoading } = useReopenBriefing(isHolidayPeriod && briefingRequested)

  // State for position dialog triggered from search/watchlist actions
  const [quickAddStock, setQuickAddStock] = useState<{ symbol: string; name: string; board: string } | null>(null)
  const [positionDialogOpen, setPositionDialogOpen] = useState(false)

  // State for watchlist removal confirmation
  const [removeTarget, setRemoveTarget] = useState<{ symbol: string; name: string } | null>(null)

  // Collapsible section state
  const [alertsOpen, setAlertsOpen] = useState(false)
  const [holidayOpen, setHolidayOpen] = useState(false)

  const realtimeMap = useMemo(
    () => new Map<string, RealtimeQuote>(realtimeData?.map((q) => [q.symbol, q]) ?? []),
    [realtimeData]
  )

  const symbols = useMemo(() => stocks?.map((s) => s.symbol) ?? [], [stocks])
  const { data: pulseData } = useMarketPulse(symbols)
  const { data: unreadCount } = useUnreadCount()

  const portfolioSymbols = useMemo(() => portfolioPositions.map((p) => p.symbol), [portfolioPositions])
  const portfolioSummary = useMemo(
    () => portfolioEmpty ? null : computePortfolioSummary(portfolioPositions, realtimeMap),
    [portfolioPositions, portfolioEmpty, realtimeMap],
  )

  // Portfolio ⊆ Watchlist: ensure every held stock is also in watchlist
  const syncedRef = useRef(false)
  useEffect(() => {
    if (syncedRef.current || !stocks || portfolioEmpty) return
    syncedRef.current = true

    const watchlistSymbols = new Set(stocks.map((s) => s.symbol))
    const missing = portfolioPositions.filter((p) => !watchlistSymbols.has(p.symbol))
    for (const pos of missing) {
      addWatchlistMutation.mutate({ symbol: pos.symbol, name: pos.name, board: pos.board })
    }
  }, [stocks, portfolioPositions, portfolioEmpty, addWatchlistMutation])

  const handleSearchSelect = (item: StockSearchItem) => {
    navigate(`/stock/${item.symbol}`)
  }

  const handleRequestAddPosition = (stock: { symbol: string; name: string; board: string }) => {
    setQuickAddStock(stock)
    setPositionDialogOpen(true)
  }

  const handlePositionSubmit = (pos: Omit<import("@/types/portfolio").Position, "id">) => {
    addPosition(pos)
    toast.success(`已添加持仓 ${pos.name}`)
  }

  const confirmWatchlistRemove = () => {
    if (removeTarget) {
      removeMutation.mutate(removeTarget.symbol, {
        onSuccess: () => {
          toast.success(`已移除 ${removeTarget.name}`)
          setRemoveTarget(null)
        },
        onError: () => {
          toast.error("移除失败，请重试")
          setRemoveTarget(null)
        },
      })
    }
  }

  return (
    <div className="space-y-7">
      {/* Header — minimal */}
      <div className="flex items-center justify-between gap-5">
        <h1 className="text-headline">概览</h1>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <PhaseIndicator />
          {realtimeData && (
            <Badge variant="outline" className="gap-1.5 text-xs h-6">
              <span className={`live-dot ${realtimeFetching ? "live-dot-warning" : ""}`} />
              实时
            </Badge>
          )}
          <span className="font-numeric text-micro">{clock.toLocaleTimeString("zh-CN")}</span>
        </div>
      </div>

      {/* Hero: Agent Briefing — replaces MarketOverview + AI Briefing */}
      <AgentBriefingCard />

      {/* Capital Flow Gauge — macro capital environment thermometer */}
      <CapitalFlowGauge />

      {/* Context: Portfolio + Market Pulse side by side */}
      {(portfolioSummary || (pulseData?.hot_events?.length ?? 0) > 0 || (unreadCount ?? 0) > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          {/* Portfolio panorama */}
          {portfolioSummary && (
            <Card>
              <CardContent className="py-4 px-5">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-caption text-muted-foreground">持仓概览</span>
                  <Link
                    to="/portfolio"
                    className="flex items-center gap-1 text-xs text-primary hover:text-primary/80 transition-colors"
                  >
                    详情 <ArrowRight className="h-3 w-3" />
                  </Link>
                </div>
                <div className="flex items-baseline gap-3">
                  <span className={`price-lg ${portfolioSummary.totalPnL > 0 ? "text-market-up" : portfolioSummary.totalPnL < 0 ? "text-market-down" : ""}`}>
                    {portfolioSummary.totalPnL > 0 ? "+" : ""}{portfolioSummary.totalPnL.toFixed(0)}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    总市值 ¥{portfolioSummary.totalMarketValue.toFixed(0)}
                  </span>
                  <span className={`pct-badge ${portfolioSummary.totalPnLPercent > 0 ? "text-market-up" : portfolioSummary.totalPnLPercent < 0 ? "text-market-down" : ""}`}>
                    {portfolioSummary.totalPnLPercent > 0 ? "+" : ""}{portfolioSummary.totalPnLPercent.toFixed(2)}%
                  </span>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Market pulse */}
          <Card className="bg-muted/30">
            <CardContent className="py-4 px-5">
              <div className="flex items-center justify-between mb-3">
                <span className="text-caption text-muted-foreground">市场脉搏</span>
                <Link
                  to="/market"
                  className="flex items-center gap-1 text-xs text-primary hover:text-primary/80 transition-colors"
                >
                  全景 <ArrowRight className="h-3 w-3" />
                </Link>
              </div>
              <div className="space-y-1.5 text-xs">
                {(pulseData?.hot_events ?? []).length > 0 && (
                  <div className="flex items-center gap-1.5">
                    <Radio className="h-3 w-3 text-warning shrink-0" />
                    <span className="truncate text-muted-foreground">
                      {pulseData!.hot_events[0].title}
                    </span>
                  </div>
                )}
                {(unreadCount ?? 0) > 0 && (
                  <div className="flex items-center gap-1.5 text-muted-foreground">
                    <Bell className="h-3 w-3" />
                    <span>{unreadCount} 条未读通知</span>
                  </div>
                )}
                {(pulseData?.hot_events ?? []).length === 0 && (unreadCount ?? 0) === 0 && (
                  <span className="text-muted-foreground">暂无市场热点</span>
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Holiday Reopen Briefing — only during genuine holiday periods (3+ consecutive non-trading days) */}
      {calendarInfo?.is_holiday_period && (
        <Collapsible open={holidayOpen} onOpenChange={setHolidayOpen}>
          <CollapsibleTrigger asChild>
            <button className="flex w-full items-center justify-between rounded-lg border border-warning/20 bg-warning/5 px-4 py-2.5 text-sm hover:bg-warning/10 transition-colors">
              <span className="flex items-center gap-2 font-medium">
                <CalendarOff className="h-4 w-4 text-warning" />
                假期研判
                <Badge variant="outline" className="text-[10px] border-warning/30 text-warning">
                  休市中
                </Badge>
              </span>
              <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform ${holidayOpen ? "rotate-180" : ""}`} />
            </button>
          </CollapsibleTrigger>
          <CollapsibleContent className="pt-2">
            <Card className="border-warning/20 bg-warning/5">
              <CardContent className="pt-4">
                {!briefingRequested ? (
                  <div className="flex items-center justify-between">
                    <p className="text-xs text-muted-foreground">
                      当前处于休市期间，可生成节后开盘综合研判报告
                    </p>
                    <Button size="sm" variant="outline" onClick={() => setBriefingRequested(true)}>
                      生成研判报告
                    </Button>
                  </div>
                ) : briefingLoading ? (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground py-2">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    正在综合全球市场与舆情数据，生成研判报告...
                  </div>
                ) : briefingData?.status === "success" ? (
                  <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <Badge variant={
                        briefingData.market_outlook === "bullish" ? "default" :
                        briefingData.market_outlook === "bearish" ? "destructive" : "secondary"
                      } className="text-[10px]">
                        {briefingData.market_outlook === "bullish" ? "偏多" :
                         briefingData.market_outlook === "bearish" ? "偏空" : "中性"}
                      </Badge>
                      <span className="text-xs text-muted-foreground">
                        置信度: {Math.round(briefingData.confidence * 100)}%
                      </span>
                    </div>
                    <p className="text-body leading-relaxed">{briefingData.summary}</p>
                    {briefingData.key_events.length > 0 && (
                      <div className="text-xs text-muted-foreground">
                        <span className="font-medium">关键事件: </span>
                        {briefingData.key_events.join(" | ")}
                      </div>
                    )}
                    {briefingData.recommendations.length > 0 && (
                      <ul className="space-y-0.5">
                        {briefingData.recommendations.map((r, i) => (
                          <li key={i} className="text-xs flex items-start gap-1">
                            <span className="text-warning mt-0.5">•</span> {r}
                          </li>
                        ))}
                      </ul>
                    )}
                    <p className="text-[10px] text-muted-foreground/40 pt-1">
                      {briefingData.disclaimer}
                    </p>
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">研判报告暂时不可用，请稍后重试</p>
                )}
              </CardContent>
            </Card>
          </CollapsibleContent>
        </Collapsible>
      )}

      {/* Smart Alerts — collapsed by default, portfolio-aware */}
      {!portfolioEmpty && (
        <Collapsible open={alertsOpen} onOpenChange={setAlertsOpen}>
          <CollapsibleTrigger asChild>
            <button className="flex w-full items-center justify-between rounded-lg border bg-card px-4 py-2.5 text-sm hover:bg-muted/50 transition-colors">
              <span className="flex items-center gap-2 font-medium">
                <Bell className="h-4 w-4 text-warning" />
                智能提醒
              </span>
              <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform ${alertsOpen ? "rotate-180" : ""}`} />
            </button>
          </CollapsibleTrigger>
          <CollapsibleContent className="pt-2">
            <SmartAlerts symbols={portfolioSymbols} />
          </CollapsibleContent>
        </Collapsible>
      )}

      {/* Search bar */}
      <div className="flex items-center justify-between gap-4">
        <StockSearch onSelect={handleSearchSelect} showAddButton onRequestAddPosition={handleRequestAddPosition} />
        {stocks && stocks.length > 0 && (
          <SummaryBar stocks={stocks} realtimeMap={realtimeMap} />
        )}
      </div>

      {/* Main Content: Watchlist */}
      {error && (
        <div className="rounded-lg border border-destructive p-4 text-sm text-destructive">
          加载失败: {error.message}
        </div>
      )}

      {/* Unified tracked stocks list (watchlist + portfolio merged) */}
      <TrackedStocksList />

      {/* Hot stock recommendations when watchlist is empty */}
      {!isLoading && stocks && stocks.length === 0 && (
        <HotStockRecommend
          onAddToWatchlist={(stock) => {
            handleSearchSelect({ ...stock, symbol: stock.symbol, name: stock.name } as StockSearchItem)
          }}
        />
      )}

      {/* Position dialog triggered from search/watchlist actions */}
      <AddPositionDialog
        open={positionDialogOpen}
        onOpenChange={(open) => {
          setPositionDialogOpen(open)
          if (!open) setQuickAddStock(null)
        }}
        onSubmit={handlePositionSubmit}
        preselectedStock={quickAddStock}
      />

      {/* Watchlist removal confirmation */}
      <ConfirmDialog
        open={!!removeTarget}
        onOpenChange={(open) => !open && setRemoveTarget(null)}
        title={`移除自选 — ${removeTarget?.name ?? ""}`}
        description={
          portfolioPositions.some((p) => p.symbol === removeTarget?.symbol)
            ? `确定要从自选列表中移除 ${removeTarget?.name}(${removeTarget?.symbol}) 吗？该股票在您的持仓中，移除自选不会影响持仓记录。`
            : `确定要从自选列表中移除 ${removeTarget?.name}(${removeTarget?.symbol}) 吗？`
        }
        confirmLabel="移除"
        variant="destructive"
        onConfirm={confirmWatchlistRemove}
        loading={removeMutation.isPending}
      />
    </div>
  )
}
