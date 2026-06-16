import { useCallback, useMemo, useState } from "react"
import { Link, useParams, useSearchParams } from "react-router-dom"
import { Star, StarOff, Briefcase, BrainCircuit } from "lucide-react"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Badge } from "@/components/ui/badge"
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
import { ResearchPanel } from "@/components/stock/ResearchPanel"
import { AlertBanner } from "@/components/stock/AlertBanner"
import { AIOverviewTab } from "@/components/stock/AIOverviewTab"
import { TechnicalTab } from "@/components/stock/TechnicalTab"
import { AgentConversationCard } from "@/components/agent/AgentConversationCard"
import { CapitalFlowTab } from "@/components/stock/CapitalFlowTab"
import { useStockConcepts } from "@/hooks/useConcept"
import { useChatStore } from "@/stores/chatStore"
import { toast } from "sonner"
import type { RealtimeQuote } from "@/types/market"
import type { Position } from "@/types/portfolio"
import type { StockConceptItem } from "@/types/concept"

function ConceptBadgeRow({
  symbol,
  onNavigateToConcepts,
}: {
  symbol: string
  onNavigateToConcepts: () => void
}) {
  const { data, isLoading } = useStockConcepts(symbol)

  if (isLoading) {
    return (
      <div className="flex items-center gap-1.5 pt-2 border-t">
        <Skeleton className="h-5 w-16" />
        <Skeleton className="h-5 w-20" />
        <Skeleton className="h-5 w-20" />
      </div>
    )
  }

  if (!data || data.concepts.length === 0) return null

  const hasLiveData = (c: StockConceptItem) =>
    c.pct_change !== 0 || c.up_count > 0 || c.down_count > 0

  const formatPct = (val: number) => `${val > 0 ? "+" : ""}${val.toFixed(2)}%`

  const pctColor = (val: number) =>
    val > 0 ? "text-market-up" : val < 0 ? "text-market-down" : "text-muted-foreground"

  const resonanceCfg = data.resonance.level !== "none"
    ? { strong: "text-market-up", moderate: "text-warning", weak: "text-warning/70" }[data.resonance.level]
    : null

  return (
    <div className="flex flex-wrap items-center gap-1.5 pt-2 border-t">
      {data.industry && (
        <>
          <Badge variant="secondary" className="text-xs">{data.industry}</Badge>
          <span className="text-xs text-muted-foreground">|</span>
        </>
      )}
      {data.concepts.slice(0, 5).map((c) => (
        <Badge
          key={c.code || c.name}
          variant="outline"
          className="text-xs gap-1 cursor-pointer hover:bg-muted/50"
          onClick={onNavigateToConcepts}
        >
          {c.name}
          {hasLiveData(c) && (
            <span className={pctColor(c.pct_change)}>{formatPct(c.pct_change)}</span>
          )}
        </Badge>
      ))}
      {data.concepts.length > 5 && (
        <span
          className="text-xs text-muted-foreground cursor-pointer hover:text-foreground"
          onClick={onNavigateToConcepts}
        >
          +{data.concepts.length - 5} 更多
        </span>
      )}
      {resonanceCfg && (
        <Badge variant="outline" className={`text-[10px] ${resonanceCfg}`}>
          {data.resonance.level === "strong" ? "强共振" : data.resonance.level === "moderate" ? "共振" : "弱共振"}
        </Badge>
      )}
    </div>
  )
}

export default function StockDetail() {
  const { symbol = "" } = useParams<{ symbol: string }>()
  const [searchParams] = useSearchParams()
  const fromPortfolio = searchParams.get("from") === "portfolio"
  const fromMarket = searchParams.get("from") === "market"
  const { data: stock, isLoading: loadingStock } = useStockDetail(symbol)
  const { data: realtimeData } = useRealtimeQuotes()
  const { data: watchlist = [] } = useWatchlist()
  const { positions, addPosition } = usePortfolio()
  const addWatchlistMutation = useAddToWatchlist()
  const removeWatchlistMutation = useRemoveFromWatchlist()
  const openChatWithContext = useChatStore((s) => s.openChatWithContext)
  const [positionDialogOpen, setPositionDialogOpen] = useState(false)
  const initialTab = searchParams.get("tab") ?? "kline"
  const [activeTab, setActiveTab] = useState(initialTab)

  // v22.0: Intel context from Intelligence Hub push flow
  const intelParam = searchParams.get("intel")
  const intelContext = useMemo(() => {
    if (!intelParam) return undefined
    return { item_ids: intelParam.split(",").filter(Boolean) }
  }, [intelParam])

  const isInWatchlist = watchlist.some((w) => w.symbol === symbol)
  const currentPosition = positions.find((p) => p.symbol === symbol) ?? null
  const isInPortfolio = currentPosition !== null

  const realtimeQuote = useMemo<RealtimeQuote | null>(() => {
    if (!realtimeData) return null
    return realtimeData.find((q) => q.symbol === symbol) ?? null
  }, [realtimeData, symbol])

  // Memoize to avoid re-triggering AddPositionDialog's useEffect on every render
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
        <Skeleton className="h-[620px] w-full rounded-lg" />
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
                <Link to={fromPortfolio ? "/portfolio" : fromMarket ? "/market" : "/"}>{fromPortfolio ? "持仓中心" : fromMarket ? "市场" : "概览"}</Link>
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

      {/* Alerts */}
      <AlertBanner symbol={symbol} />

      {/* Price Header + Concept Tags */}
      <div className="rounded-md border p-5 space-y-0">
        <RealtimePriceHeader stock={stock} realtimeQuote={realtimeQuote} />
        <ConceptBadgeRow symbol={symbol} onNavigateToConcepts={() => setActiveTab("concept")} />
      </div>

      {/* Position Context — when stock is held */}
      {currentPosition && (
        <PositionContextCard position={currentPosition} quote={realtimeQuote} />
      )}

      {/* Main Content: Agent judgment + Evidence tabs */}
      <div className="space-y-5">
        {/* Hero: Agent judgment + conversation */}
        <AgentConversationCard
          symbol={symbol}
          position={currentPosition ? { cost_price: currentPosition.costPrice, shares: currentPosition.shares } : undefined}
          intelContext={intelContext}
        />

        {/* Evidence Tabs */}
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList variant="line" className="justify-start">
            <TabsTrigger value="kline">图表</TabsTrigger>
            <TabsTrigger value="concept">背景</TabsTrigger>
            <TabsTrigger value="capital-flow">资金流</TabsTrigger>
            <TabsTrigger value="research">资讯</TabsTrigger>
          </TabsList>

          {/* ===== Tab 1: K线与技术 (chart + indicators + fund flow + dragon tiger + move analysis) ===== */}
          <TabsContent value="kline" className="mt-3">
            {activeTab === "kline" && (
              <TechnicalTab
                symbol={symbol}
                realtimeQuote={realtimeQuote}
                currentPosition={currentPosition}
              />
            )}
          </TabsContent>

          {/* ===== Tab 2: 概念与行业 (concepts + cross-market + holiday research + AI Q&A) ===== */}
          <TabsContent value="concept" className="mt-3">
            {activeTab === "concept" && (
              <AIOverviewTab
                symbol={symbol}
                stockName={stock.name}
                hasPosition={isInPortfolio}
              />
            )}
          </TabsContent>

          {/* ===== Tab 3: 资金流向 (capital flow breakdown) ===== */}
          <TabsContent value="capital-flow" className="mt-3">
            {activeTab === "capital-flow" && (
              <CapitalFlowTab symbol={symbol} />
            )}
          </TabsContent>

          {/* ===== Tab 4: 资讯 (news + research) ===== */}
          <TabsContent value="research" className="mt-3">
            <ResearchPanel symbol={symbol} />
          </TabsContent>
        </Tabs>
      </div>

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
