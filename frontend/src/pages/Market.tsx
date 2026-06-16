import { useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { formatDateTime } from "@/lib/formatters"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Skeleton } from "@/components/ui/skeleton"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { AddPositionDialog } from "@/components/portfolio/AddPositionDialog"
import { MarketOverview } from "@/components/stock/MarketOverview"
import { GlobalMarketPanel } from "@/components/dashboard/GlobalMarketPanel"
import { useDragonTiger, useLimitUp, useTradingCalendar } from "@/hooks/useMarket"
import { useAddToWatchlist, useWatchlist } from "@/hooks/useStocks"
import { usePortfolio, detectBoard } from "@/hooks/usePortfolio"
import { DragonTigerSummary, LimitUpSummary } from "@/components/market/MarketSummaryCards"
import { SentimentTab } from "@/components/market/SentimentTab"
import { SectorFlowTab } from "@/components/market/SectorFlowHeatmap"
import {
  MoreHorizontal, Eye, Star, Briefcase, Check, Calendar,
  Flame, TrendingUp, TrendingDown,
} from "lucide-react"
import { useConceptHot } from "@/hooks/useConcept"
import type { ConceptHeatItem } from "@/types/concept"
import { toast } from "sonner"
import type { Position } from "@/types/portfolio"
import { formatAmount, formatPercent } from "@/lib/formatters"

/** Badge variant for dragon-tiger reason text */
function reasonBadgeColor(reason: string | null): string {
  if (!reason) return "text-muted-foreground"
  if (reason.includes("涨幅偏离") || reason.includes("连续")) return "text-market-up border-market-up/30 bg-market-up/5"
  if (reason.includes("跌幅偏离")) return "text-market-down border-market-down/30 bg-market-down/5"
  if (reason.includes("换手率")) return "text-warning border-warning/30 bg-warning/5"
  if (reason.includes("振幅")) return "text-accent-primary border-accent-primary/30 bg-accent-primary/5"
  return "text-muted-foreground"
}

function RowActions({
  symbol,
  watchlistSymbols,
  onNavigate,
  onAddWatchlist,
  onAddPosition,
}: {
  symbol: string
  watchlistSymbols: Set<string>
  onNavigate: () => void
  onAddWatchlist: () => void
  onAddPosition: () => void
}) {
  const alreadyInWatchlist = watchlistSymbols.has(symbol)

  return (
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
        <DropdownMenuItem onClick={onNavigate}>
          <Eye className="h-4 w-4" />
          查看详情
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        {alreadyInWatchlist ? (
          <DropdownMenuItem disabled>
            <Check className="h-4 w-4" />
            已在自选
          </DropdownMenuItem>
        ) : (
          <DropdownMenuItem onClick={onAddWatchlist}>
            <Star className="h-4 w-4" />
            添加自选
          </DropdownMenuItem>
        )}
        <DropdownMenuItem onClick={onAddPosition}>
          <Briefcase className="h-4 w-4" />
          添加持仓
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

const SESSION_LABELS: Record<string, string> = {
  pre_market: "盘前",
  morning: "上午盘",
  lunch_break: "午间休市",
  afternoon: "下午盘",
  after_hours: "盘后",
  closed: "已收盘",
  auction: "集合竞价",
  auction_freeze: "竞价冻结",
  lunch: "午间休市",
  closing_auction: "尾盘竞价",
  non_trading: "非交易日",
}

function TradingCalendarCard() {
  const { data: calendar } = useTradingCalendar()
  if (!calendar) return <Skeleton className="h-32 w-full rounded-lg" />
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-1.5">
          <Calendar className="h-4 w-4 text-primary" />
          交易日历
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <div className="flex justify-between">
          <span className="text-muted-foreground">今日</span>
          <span>{calendar.date}{calendar.is_trading_day ? "" : " (非交易日)"}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">当前时段</span>
          <Badge variant={calendar.is_trading_day ? "default" : "secondary"} className="text-xs">
            {SESSION_LABELS[calendar.current_session] ?? calendar.current_session}
          </Badge>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">下一交易日</span>
          <span>{calendar.next_trading_day}</span>
        </div>
        {calendar.is_holiday_period && (
          <Badge variant="outline" className="text-xs border-warning/30 text-warning w-fit">
            休市期间
          </Badge>
        )}
      </CardContent>
    </Card>
  )
}

function HeatBar({ score }: { score: number }) {
  const color = score >= 70 ? "bg-danger" : score >= 40 ? "bg-warning" : "bg-info"
  return (
    <div className="flex items-center gap-1.5">
      <div className="h-1.5 w-16 rounded-full bg-muted overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${color}`}
          style={{ width: `${Math.min(score, 100)}%` }}
        />
      </div>
      <span className="text-[10px] font-numeric text-muted-foreground">{score.toFixed(0)}</span>
    </div>
  )
}

function ConceptHeatRow({ item, rank, onNavigate }: { item: ConceptHeatItem; rank: number; onNavigate: (symbol: string) => void }) {
  const pctColor = item.pct_change > 0 ? "text-market-up" : item.pct_change < 0 ? "text-market-down" : "text-muted-foreground"
  const PctIcon = item.pct_change > 0 ? TrendingUp : item.pct_change < 0 ? TrendingDown : null
  return (
    <tr className="border-b data-row-hover">
      <td className="py-2 pr-3">
        <span className={`text-xs font-numeric ${rank <= 3 ? "text-market-up font-bold" : "text-muted-foreground"}`}>
          {rank}
        </span>
      </td>
      <td className="py-2 pr-3">
        <span className="text-sm font-medium">{item.name}</span>
        <span className="text-[10px] text-muted-foreground ml-1.5">{item.code}</span>
      </td>
      <td className={`py-2 pr-3 text-right col-numeric text-sm ${pctColor}`}>
        <span className="inline-flex items-center gap-0.5">
          {PctIcon && <PctIcon className="h-3 w-3" />}
          {formatPercent(item.pct_change)}
        </span>
      </td>
      <td className="py-2 pr-3 text-right">
        <HeatBar score={item.heat_score} />
      </td>
      <td className="py-2 pr-3 text-right">
        <span className="text-market-up text-xs">{item.up_count}</span>
        <span className="text-muted-foreground text-xs mx-0.5">/</span>
        <span className="text-market-down text-xs">{item.down_count}</span>
      </td>
      <td className="py-2 pr-3 text-right col-numeric text-xs">
        {formatAmount(item.amount)}
      </td>
      <td className="py-2 pr-3">
        {item.leader.symbol ? (
          <button
            onClick={() => onNavigate(item.leader.symbol)}
            className="inline-flex items-center gap-1 text-xs hover:text-primary transition-colors"
          >
            <span className="font-medium">{item.leader.name}</span>
            <span className={`font-numeric ${(item.leader.pct_change ?? 0) >= 0 ? "text-market-up" : "text-market-down"}`}>
              {formatPercent(item.leader.pct_change)}
            </span>
          </button>
        ) : (
          <span className="text-xs text-muted-foreground">-</span>
        )}
      </td>
    </tr>
  )
}

/* ─── Lazy tab content components ─────────────────────────────────── */

function ConceptHeatTabContent({
  navigate,
}: {
  navigate: (path: string) => void
}) {
  const { data: conceptHot, isLoading: chLoading } = useConceptHot(30)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-1.5">
          <Flame className="h-5 w-5 text-warning" />
          概念板块热度排行
        </CardTitle>
        {conceptHot?.updated_at && (
          <p className="text-xs text-muted-foreground">更新于 {formatDateTime(conceptHot.updated_at)}</p>
        )}
      </CardHeader>
      <CardContent>
        {chLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : !conceptHot?.items.length ? (
          <p className="text-muted-foreground py-8 text-center">暂无概念板块数据</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full data-table">
              <thead>
                <tr className="border-b text-left text-muted-foreground text-xs">
                  <th className="py-2 pr-3 w-8">#</th>
                  <th className="py-2 pr-3">板块名称</th>
                  <th className="py-2 pr-3 text-right">涨跌幅</th>
                  <th className="py-2 pr-3 text-right">热度</th>
                  <th className="py-2 pr-3 text-right">涨/跌</th>
                  <th className="py-2 pr-3 text-right">成交额</th>
                  <th className="py-2 pr-3">领涨股</th>
                </tr>
              </thead>
              <tbody>
                {conceptHot.items.map((item, i) => (
                  <ConceptHeatRow
                    key={item.code}
                    item={item}
                    rank={i + 1}
                    onNavigate={(sym) => navigate(`/stock/${sym}?from=market`)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function DragonTigerTabContent({
  watchlistSymbols,
  navigate,
  onAddWatchlist,
  onAddPosition,
}: {
  watchlistSymbols: Set<string>
  navigate: (path: string) => void
  onAddWatchlist: (symbol: string, name: string) => void
  onAddPosition: (symbol: string, name: string) => void
}) {
  const { data: dragonTiger, isLoading: dtLoading } = useDragonTiger()

  return (
    <>
      {dragonTiger && dragonTiger.length > 0 && (
        <DragonTigerSummary data={dragonTiger} />
      )}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">龙虎榜 — 机构资金动向</CardTitle>
        </CardHeader>
        <CardContent>
          {dtLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : !dragonTiger?.length ? (
            <p className="text-muted-foreground py-8 text-center">今日暂无龙虎榜数据</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full data-table">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="py-2 pr-4">代码</th>
                    <th className="py-2 pr-4">名称</th>
                    <th className="py-2 pr-4 text-right">涨跌幅</th>
                    <th className="py-2 pr-4 text-right">净买入</th>
                    <th className="py-2 pr-4 text-right">买入额</th>
                    <th className="py-2 pr-4 text-right">卖出额</th>
                    <th className="py-2 pr-4">上榜原因</th>
                    <th className="py-2 pr-4 text-right w-12">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {dragonTiger.map((item, i) => (
                    <tr key={`${item.symbol}-${i}`} className="border-b data-row-hover">
                      <td className="py-2 pr-4">
                        <Link
                          to={`/stock/${item.symbol}?from=market`}
                          className="font-mono text-primary hover:underline"
                        >
                          {item.symbol}
                        </Link>
                      </td>
                      <td className="py-2 pr-4 font-medium">{item.name}</td>
                      <td className={`py-2 pr-4 text-right col-numeric ${
                        (item.pct_change ?? 0) >= 0 ? "text-market-up" : "text-market-down"
                      }`}>
                        {formatPercent(item.pct_change)}
                      </td>
                      <td className={`py-2 pr-4 text-right col-numeric ${
                        (item.net_buy ?? 0) >= 0 ? "text-market-up" : "text-market-down"
                      }`}>
                        {formatAmount(item.net_buy)}
                      </td>
                      <td className="py-2 pr-4 text-right col-numeric text-market-up">
                        {formatAmount(item.buy_amount)}
                      </td>
                      <td className="py-2 pr-4 text-right col-numeric text-market-down">
                        {formatAmount(item.sell_amount)}
                      </td>
                      <td className="py-2 pr-4 max-w-[220px]">
                        {item.reason ? (
                          <Badge
                            variant="outline"
                            className={`text-xs truncate max-w-full ${reasonBadgeColor(item.reason)}`}
                          >
                            {item.reason}
                          </Badge>
                        ) : (
                          <span className="text-xs text-muted-foreground">-</span>
                        )}
                      </td>
                      <td className="py-2 pr-4 text-right">
                        <RowActions
                          symbol={item.symbol}
                          watchlistSymbols={watchlistSymbols}
                          onNavigate={() => navigate(`/stock/${item.symbol}?from=market`)}
                          onAddWatchlist={() => onAddWatchlist(item.symbol, item.name)}
                          onAddPosition={() => onAddPosition(item.symbol, item.name)}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </>
  )
}

function LimitUpTabContent({
  watchlistSymbols,
  navigate,
  onAddWatchlist,
  onAddPosition,
}: {
  watchlistSymbols: Set<string>
  navigate: (path: string) => void
  onAddWatchlist: (symbol: string, name: string) => void
  onAddPosition: (symbol: string, name: string) => void
}) {
  const { data: limitUp, isLoading: luLoading } = useLimitUp()

  return (
    <>
      {limitUp && limitUp.length > 0 && (
        <LimitUpSummary data={limitUp} />
      )}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">涨停板 — 强势股追踪</CardTitle>
        </CardHeader>
        <CardContent>
          {luLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : !limitUp?.length ? (
            <p className="text-muted-foreground py-8 text-center">今日暂无涨停数据</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full data-table">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="py-2 pr-4">代码</th>
                    <th className="py-2 pr-4">名称</th>
                    <th className="py-2 pr-4 text-right">涨跌幅</th>
                    <th className="py-2 pr-4 text-right">最新价</th>
                    <th className="py-2 pr-4 text-right">成交额</th>
                    <th className="py-2 pr-4 text-right">封板资金</th>
                    <th className="py-2 pr-4 text-center">连板</th>
                    <th className="py-2 pr-4 text-right">首封时间</th>
                    <th className="py-2 pr-4">行业</th>
                    <th className="py-2 pr-4 text-right w-12">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {limitUp.map((item, i) => (
                    <tr key={`${item.symbol}-${i}`} className="border-b data-row-hover">
                      <td className="py-2 pr-4">
                        <Link
                          to={`/stock/${item.symbol}?from=market`}
                          className="font-mono text-primary hover:underline"
                        >
                          {item.symbol}
                        </Link>
                      </td>
                      <td className="py-2 pr-4 font-medium">{item.name}</td>
                      <td className="py-2 pr-4 text-right col-numeric text-market-up">
                        {formatPercent(item.pct_change)}
                      </td>
                      <td className="py-2 pr-4 text-right col-numeric">
                        {item.price?.toFixed(2) ?? "-"}
                      </td>
                      <td className="py-2 pr-4 text-right col-numeric">
                        {formatAmount(item.amount)}
                      </td>
                      <td className="py-2 pr-4 text-right col-numeric">
                        {formatAmount(item.seal_amount)}
                      </td>
                      <td className="py-2 pr-4 text-center">
                        {item.consecutive && item.consecutive > 1 ? (
                          <Badge variant="destructive">{item.consecutive}连板</Badge>
                        ) : (
                          <Badge variant="outline">首板</Badge>
                        )}
                      </td>
                      <td className="py-2 pr-4 text-right col-numeric text-xs">
                        {item.first_seal_time || "-"}
                      </td>
                      <td className="py-2 pr-4">
                        {item.industry ? (
                          <Badge variant="secondary" className="text-xs">
                            {item.industry}
                          </Badge>
                        ) : (
                          <span className="text-xs text-muted-foreground">-</span>
                        )}
                      </td>
                      <td className="py-2 pr-4 text-right">
                        <RowActions
                          symbol={item.symbol}
                          watchlistSymbols={watchlistSymbols}
                          onNavigate={() => navigate(`/stock/${item.symbol}?from=market`)}
                          onAddWatchlist={() => onAddWatchlist(item.symbol, item.name)}
                          onAddPosition={() => onAddPosition(item.symbol, item.name)}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </>
  )
}

/* ─── Main Market Component ───────────────────────────────────────── */

export default function Market() {
  const [tab, setTab] = useState("overview")
  const { data: watchlist = [] } = useWatchlist()
  const addWatchlistMutation = useAddToWatchlist()
  const { addPosition } = usePortfolio()
  const navigate = useNavigate()

  const [positionTarget, setPositionTarget] = useState<{ symbol: string; name: string; board: string } | null>(null)
  const [positionDialogOpen, setPositionDialogOpen] = useState(false)

  const watchlistSymbols = new Set(watchlist.map((w) => w.symbol))

  const handleAddWatchlist = (symbol: string, name: string) => {
    addWatchlistMutation.mutate(
      { symbol, name, board: detectBoard(symbol) },
      {
        onSuccess: () => {
          toast.success(`已添加 ${name} 到自选`, {
            action: {
              label: "添加持仓",
              onClick: () => {
                setPositionTarget({ symbol, name, board: detectBoard(symbol) })
                setPositionDialogOpen(true)
              },
            },
          })
        },
        onError: () => toast.error("添加失败，请重试"),
      },
    )
  }

  const handleAddPosition = (symbol: string, name: string) => {
    setPositionTarget({ symbol, name, board: detectBoard(symbol) })
    setPositionDialogOpen(true)
  }

  const handlePositionSubmit = (pos: Omit<Position, "id">) => {
    addPosition(pos)
    const isInWatchlist = watchlistSymbols.has(pos.symbol)
    if (!isInWatchlist) {
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
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-headline">市场</h1>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList variant="line">
          <TabsTrigger value="overview">市场总览</TabsTrigger>
          <TabsTrigger value="concept-heat">概念热度</TabsTrigger>
          <TabsTrigger value="dragon-tiger">龙虎榜</TabsTrigger>
          <TabsTrigger value="limit-up">涨停板</TabsTrigger>
          <TabsTrigger value="capital-flow">资金流向</TabsTrigger>
          <TabsTrigger value="sentiment">舆情热点</TabsTrigger>
        </TabsList>

        {/* Overview — always mounted (default tab) */}
        <TabsContent value="overview" className="space-y-4">
          <MarketOverview />
          <GlobalMarketPanel />
          <TradingCalendarCard />
        </TabsContent>

        {/* Concept Heat — lazy rendered */}
        {tab === "concept-heat" && (
          <TabsContent value="concept-heat">
            <ConceptHeatTabContent navigate={(p) => navigate(p)} />
          </TabsContent>
        )}

        {/* Dragon Tiger — lazy rendered */}
        {tab === "dragon-tiger" && (
          <TabsContent value="dragon-tiger">
            <DragonTigerTabContent
              watchlistSymbols={watchlistSymbols}
              navigate={(p) => navigate(p)}
              onAddWatchlist={handleAddWatchlist}
              onAddPosition={handleAddPosition}
            />
          </TabsContent>
        )}

        {/* Limit Up — lazy rendered */}
        {tab === "limit-up" && (
          <TabsContent value="limit-up">
            <LimitUpTabContent
              watchlistSymbols={watchlistSymbols}
              navigate={(p) => navigate(p)}
              onAddWatchlist={handleAddWatchlist}
              onAddPosition={handleAddPosition}
            />
          </TabsContent>
        )}

        {/* Capital Flow — lazy rendered */}
        {tab === "capital-flow" && (
          <TabsContent value="capital-flow" className="space-y-5">
            <SectorFlowTab />
          </TabsContent>
        )}

        {/* Sentiment — lazy rendered */}
        {tab === "sentiment" && (
          <TabsContent value="sentiment" className="space-y-5">
            <SentimentTab />
          </TabsContent>
        )}
      </Tabs>

      {/* Position Dialog */}
      <AddPositionDialog
        open={positionDialogOpen}
        onOpenChange={(open) => {
          setPositionDialogOpen(open)
          if (!open) setPositionTarget(null)
        }}
        onSubmit={handlePositionSubmit}
        preselectedStock={positionTarget}
      />
    </div>
  )
}
