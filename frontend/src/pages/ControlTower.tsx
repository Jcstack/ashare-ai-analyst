import { useMemo } from "react"
import { Link, useNavigate } from "react-router-dom"
import {
  Shield,
  TrendingUp,
  TrendingDown,
  Clock,
  Eye,
  Check,
  X,
  ArrowRight,
  Loader2,
  Activity,
  Minus,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useBootstrap, useConfirmAction, useRejectAction } from "@/hooks/useActions"
import { useMarketStatus } from "@/hooks/useMarketStatus"
import { usePortfolio, computePortfolioSummary } from "@/hooks/usePortfolio"
import { useRealtimeQuotes } from "@/hooks/useMarket"
import { cn } from "@/lib/utils"
import { toast } from "sonner"
import type { ActionItem, RegimeState } from "@/types/action"
import type { RealtimeQuote } from "@/types/market"

// ---------------------------------------------------------------------------
// Regime Bar
// ---------------------------------------------------------------------------

function RegimeBar({
  regime,
  marketLabel,
  isTrading,
}: {
  regime: RegimeState | undefined
  marketLabel: string
  isTrading: boolean
}) {
  const phase = regime?.sentiment?.phase_cn ?? "--"
  const riskRemaining = regime?.risk_budget?.remaining_pct
  const riskUsed = regime?.risk_budget?.used_pct

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border bg-card px-4 py-2.5">
      {/* Market Status */}
      <div className="flex items-center gap-1.5">
        <span
          className={cn(
            "h-2 w-2 rounded-full",
            isTrading ? "bg-green-500 animate-pulse" : "bg-muted-foreground",
          )}
        />
        <span className="text-sm font-medium">{marketLabel}</span>
      </div>

      <span className="text-muted-foreground">|</span>

      {/* Sentiment Phase */}
      <div className="flex items-center gap-1.5 text-sm">
        <Activity className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-muted-foreground">情绪:</span>
        <span className="font-medium">{phase}</span>
      </div>

      <span className="text-muted-foreground">|</span>

      {/* Risk Budget */}
      <div className="flex items-center gap-1.5 text-sm">
        <Shield className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-muted-foreground">风险余额:</span>
        {riskRemaining != null ? (
          <span
            className={cn(
              "font-medium font-numeric",
              riskRemaining > 1 ? "text-green-500" : riskRemaining > 0.5 ? "text-yellow-500" : "text-red-500",
            )}
          >
            {riskRemaining.toFixed(1)}%
          </span>
        ) : (
          <span className="text-muted-foreground">--</span>
        )}
        {riskUsed != null && (
          <span className="text-xs text-muted-foreground">(已用 {riskUsed.toFixed(1)}%)</span>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Action Card
// ---------------------------------------------------------------------------

const actionConfig = {
  buy: { icon: TrendingUp, color: "text-green-500", bg: "bg-green-500/10", label: "买入" },
  sell: { icon: TrendingDown, color: "text-red-500", bg: "bg-red-500/10", label: "卖出" },
  reduce: { icon: Minus, color: "text-yellow-500", bg: "bg-yellow-500/10", label: "减仓" },
  hold: { icon: Eye, color: "text-blue-500", bg: "bg-blue-500/10", label: "持有" },
} as const

const urgencyConfig = {
  immediate: { label: "立即", color: "text-red-500 border-red-500/30" },
  today: { label: "今日", color: "text-yellow-500 border-yellow-500/30" },
  observe: { label: "观察", color: "text-muted-foreground border-muted-foreground/30" },
} as const

function ActionCard({
  item,
  onConfirm,
  onReject,
  confirming,
  rejecting,
}: {
  item: ActionItem
  onConfirm: () => void
  onReject: () => void
  confirming: boolean
  rejecting: boolean
}) {
  const navigate = useNavigate()
  const cfg = actionConfig[item.action]
  const urgCfg = urgencyConfig[item.urgency]
  const Icon = cfg.icon
  const plan = item.execution_plan

  return (
    <Card className="transition-all hover:shadow-md">
      <CardContent className="p-4">
        <div className="flex items-start gap-3">
          {/* Action Icon */}
          <div className={cn("flex h-10 w-10 items-center justify-center rounded-lg shrink-0", cfg.bg)}>
            <Icon className={cn("h-5 w-5", cfg.color)} />
          </div>

          {/* Content */}
          <div className="flex-1 min-w-0 space-y-2">
            {/* Header row */}
            <div className="flex items-center gap-2 flex-wrap">
              <span className={cn("text-sm font-semibold", cfg.color)}>{cfg.label}</span>
              <span className="text-sm font-medium">{item.stock_name}</span>
              <span className="text-xs text-muted-foreground">{item.symbol}</span>
              <Badge variant="outline" className={cn("text-[10px]", urgCfg.color)}>
                {urgCfg.label}
              </Badge>
              <span className="text-xs font-numeric text-muted-foreground">
                置信度 {Math.round(item.confidence * 100)}%
              </span>
            </div>

            {/* Brief recommendation */}
            <p className="text-xs text-muted-foreground leading-relaxed">
              {plan.time_window && <span>{plan.time_window} | </span>}
              {plan.target_shares > 0 && <span>{plan.target_shares}股 | </span>}
              {plan.price_guidance}
            </p>

            {/* Action buttons */}
            <div className="flex items-center gap-2 pt-1">
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-xs"
                onClick={() => navigate(`/signal/${item.id}`)}
              >
                查看详情
              </Button>
              <Button
                size="sm"
                className="h-7 text-xs gap-1"
                onClick={onConfirm}
                disabled={confirming || rejecting}
              >
                {confirming ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
                确认执行
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-7 text-xs gap-1"
                onClick={onReject}
                disabled={confirming || rejecting}
              >
                {rejecting ? <Loader2 className="h-3 w-3 animate-spin" /> : <X className="h-3 w-3" />}
                暂不操作
              </Button>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Portfolio Heat
// ---------------------------------------------------------------------------

function PortfolioHeat({ realtimeMap }: { realtimeMap: Map<string, RealtimeQuote> }) {
  const { positions, isEmpty } = usePortfolio()
  const summary = useMemo(
    () => (isEmpty ? null : computePortfolioSummary(positions, realtimeMap)),
    [positions, isEmpty, realtimeMap],
  )

  if (!summary || summary.positions.length === 0) {
    return null
  }

  const totalValue = summary.totalMarketValue
  // Group positions by a basic "sector" — use board as proxy
  const sectorBlocks = summary.positions.map((p) => {
    const weight = totalValue > 0 ? (p.marketValue / totalValue) * 100 : 0
    return {
      symbol: p.symbol,
      name: p.name,
      pnlPct: p.pnlPercent,
      weight,
      marketValue: p.marketValue,
    }
  })

  return (
    <Card>
      <CardHeader className="py-3 px-4">
        <div className="flex items-center justify-between">
          <CardTitle className="text-title">持仓概览</CardTitle>
          <Link
            to="/portfolio"
            className="flex items-center gap-1 text-xs text-primary hover:text-primary/80 transition-colors"
          >
            详情 <ArrowRight className="h-3 w-3" />
          </Link>
        </div>
      </CardHeader>
      <CardContent className="px-4 pb-4 space-y-3">
        {/* Summary line */}
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
          <div>
            <span className="text-muted-foreground text-xs">总资产</span>
            <span className="ml-1.5 font-numeric font-semibold">
              ¥{summary.totalMarketValue.toLocaleString(undefined, { maximumFractionDigits: 0 })}
            </span>
          </div>
          <div>
            <span className="text-muted-foreground text-xs">浮动盈亏</span>
            <span
              className={cn(
                "ml-1.5 font-numeric",
                summary.totalPnL > 0 ? "text-market-up" : summary.totalPnL < 0 ? "text-market-down" : "",
              )}
            >
              {summary.totalPnL > 0 ? "+" : ""}
              ¥{Math.abs(summary.totalPnL).toLocaleString(undefined, { maximumFractionDigits: 0 })}
            </span>
          </div>
          <div>
            <span className="text-muted-foreground text-xs">收益率</span>
            <span
              className={cn(
                "ml-1.5 font-numeric",
                summary.totalPnLPercent > 0 ? "text-market-up" : summary.totalPnLPercent < 0 ? "text-market-down" : "",
              )}
            >
              {summary.totalPnLPercent > 0 ? "+" : ""}
              {summary.totalPnLPercent.toFixed(2)}%
            </span>
          </div>
        </div>

        {/* Heat blocks */}
        <div className="flex flex-wrap gap-1.5">
          {sectorBlocks.map((block) => (
            <Link
              key={block.symbol}
              to={`/stock/${block.symbol}?from=portfolio`}
              className={cn(
                "rounded-md px-2.5 py-1.5 text-xs transition-colors hover:opacity-80",
                block.pnlPct > 0
                  ? "bg-green-500/15 text-green-500"
                  : block.pnlPct < 0
                    ? "bg-red-500/15 text-red-500"
                    : "bg-muted text-muted-foreground",
              )}
              style={{ minWidth: `${Math.max(block.weight * 2, 60)}px` }}
            >
              <div className="font-medium truncate">{block.name}</div>
              <div className="font-numeric">
                {block.pnlPct > 0 ? "+" : ""}
                {block.pnlPct.toFixed(2)}%
              </div>
            </Link>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Recent Events
// ---------------------------------------------------------------------------

function RecentEvents({ messages }: { messages: { id: string; type: string; title: string; created_at: string }[] }) {
  if (messages.length === 0) return null

  return (
    <Card>
      <CardHeader className="py-3 px-4">
        <CardTitle className="text-title">最近事件</CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-3">
        <div className="space-y-1.5">
          {messages.slice(0, 5).map((msg) => (
            <div key={msg.id} className="flex items-center gap-2 text-xs">
              <Clock className="h-3 w-3 text-muted-foreground shrink-0" />
              <span className="text-muted-foreground font-numeric shrink-0">
                {new Date(msg.created_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}
              </span>
              <span className="truncate text-foreground">{msg.title}</span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Control Tower Page
// ---------------------------------------------------------------------------

export default function ControlTower() {
  const { data: bootstrap, isLoading, error } = useBootstrap()
  const { data: marketStatus } = useMarketStatus()
  const { positions } = usePortfolio()
  const positionSymbols = useMemo(() => positions.map((p) => p.symbol), [positions])
  const { data: realtimeData } = useRealtimeQuotes(
    positionSymbols.length > 0 ? positionSymbols : undefined,
  )
  const confirmMutation = useConfirmAction()
  const rejectMutation = useRejectAction()

  const realtimeMap = useMemo(
    () => new Map<string, RealtimeQuote>(realtimeData?.map((q) => [q.symbol, q]) ?? []),
    [realtimeData],
  )

  const isTrading = marketStatus?.is_trading ?? false
  const marketLabel = marketStatus?.label ?? "加载中"

  // Sort action queue: immediate first, then by confidence descending
  const sortedActions = useMemo(() => {
    const actions = bootstrap?.action_queue ?? []
    const urgencyOrder = { immediate: 0, today: 1, observe: 2 }
    return [...actions]
      .filter((a) => a.status === "pending")
      .sort((a, b) => {
        const urgDiff = urgencyOrder[a.urgency] - urgencyOrder[b.urgency]
        if (urgDiff !== 0) return urgDiff
        return b.confidence - a.confidence
      })
  }, [bootstrap?.action_queue])

  const handleConfirm = (id: string) => {
    confirmMutation.mutate(id, {
      onSuccess: () => toast.success("已确认执行"),
      onError: () => toast.error("确认失败，请重试"),
    })
  }

  const handleReject = (id: string) => {
    rejectMutation.mutate(id, {
      onSuccess: () => toast.success("已暂缓操作"),
      onError: () => toast.error("操作失败，请重试"),
    })
  }

  if (isLoading) {
    return (
      <div className="space-y-5">
        <Skeleton className="h-10 w-full rounded-lg" />
        <div className="space-y-3">
          <Skeleton className="h-24 w-full rounded-lg" />
          <Skeleton className="h-24 w-full rounded-lg" />
        </div>
        <Skeleton className="h-40 w-full rounded-lg" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="space-y-5">
        <RegimeBar regime={undefined} marketLabel={marketLabel} isTrading={isTrading} />
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          控制塔数据加载失败: {error.message}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-headline">控制塔</h1>
        {bootstrap?.unread_count ? (
          <Badge variant="secondary" className="text-xs">
            {bootstrap.unread_count} 条未读
          </Badge>
        ) : null}
      </div>

      {/* Regime Bar */}
      <RegimeBar regime={bootstrap?.regime} marketLabel={marketLabel} isTrading={isTrading} />

      {/* Action Queue */}
      <div className="space-y-3">
        <h2 className="text-title flex items-center gap-2">
          待执行操作
          {sortedActions.length > 0 && (
            <Badge className="text-[10px]">{sortedActions.length}</Badge>
          )}
        </h2>

        {sortedActions.length === 0 ? (
          <Card>
            <CardContent className="py-8 text-center">
              <div className="flex flex-col items-center gap-2">
                <Shield className="h-8 w-8 text-muted-foreground/40" />
                <p className="text-sm text-muted-foreground">暂无待执行操作</p>
                <p className="text-xs text-muted-foreground/60">AI 投资团队正在监控市场，有操作建议时会通知您</p>
              </div>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-2">
            {sortedActions.map((item) => (
              <ActionCard
                key={item.id}
                item={item}
                onConfirm={() => handleConfirm(item.id)}
                onReject={() => handleReject(item.id)}
                confirming={confirmMutation.isPending && confirmMutation.variables === item.id}
                rejecting={rejectMutation.isPending && rejectMutation.variables === item.id}
              />
            ))}
          </div>
        )}
      </div>

      {/* Portfolio Heat */}
      <PortfolioHeat realtimeMap={realtimeMap} />

      {/* Recent Events */}
      <RecentEvents messages={bootstrap?.recent_messages ?? []} />
    </div>
  )
}
