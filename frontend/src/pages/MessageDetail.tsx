/** MessageDetail page — detailed view for a single message.
 *
 * Renders specialized layouts for:
 * - late_session: Stock recommendation cards with buy range, position, stop loss, target
 * - post_market: P&L summary + per-stock performance table + next day plan
 * - Others: Standard content display
 *
 * Per PRD v37.0 Quant Agent Schedule.
 */

import { useEffect } from "react"
import { useParams, useNavigate } from "react-router-dom"
import {
  ArrowLeft,
  TrendingUp,
  TrendingDown,
  ShieldAlert,
  Target,
  Clock,
  AlertTriangle,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useMessageDetail, useMarkMessageRead } from "@/hooks/useMessages"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { cn } from "@/lib/utils"
import type {
  Message,
  MessageType,
  StockRecommendation,
} from "@/types/message"

// ── Type label map (same as MessageFeed) ──────────────────────

const TYPE_LABELS: Record<MessageType, string> = {
  buy_signal: "买入信号",
  sell_signal: "卖出信号",
  risk_alert: "风险提醒",
  market_watch: "市场观察",
  hold_reminder: "持仓提醒",
  pre_market: "盘前分析",
  call_auction: "集合竞价",
  intraday_signal: "盘中信号",
  late_session: "尾盘决策",
  post_market: "盘后复盘",
  holiday_intel: "假期情报",
  global_intelligence: "全球情报",
  intelligence_digest: "情报摘要",
  global_pulse: "全球脉搏",
  market_pulse: "市场脉搏",
}

// ── Helpers ───────────────────────────────────────────────────

function formatDateTime(dateStr: string): string {
  return new Date(dateStr).toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function formatPrice(value: number): string {
  return value.toFixed(2)
}

function formatPct(value: number): string {
  const sign = value >= 0 ? "+" : ""
  return `${sign}${value.toFixed(2)}%`
}

// ── Helpers: executor signal formatting ─────────────────────

function formatYuan(value: number): string {
  if (value >= 10000) {
    return `¥${(value / 10000).toFixed(2)}万`
  }
  return `¥${value.toLocaleString("zh-CN", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
}

const CONFIDENCE_STYLES: Record<string, string> = {
  高: "bg-green-500/15 text-green-400 border-green-500/30",
  中: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  低: "bg-gray-500/15 text-gray-400 border-gray-500/30",
}

// ── Late Session / Executor: Stock Recommendation Card ──────

function StockRecommendationCard({ stock }: { stock: StockRecommendation }) {
  const isSell = stock.direction === "SELL"
  const directionLabel = isSell ? "卖出" : "买入"
  const dirGradient = isSell
    ? "from-red-500/10 to-transparent border-red-500/25"
    : "from-green-500/10 to-transparent border-green-500/25"
  const dirBadge = isSell
    ? "bg-red-500 text-white border-red-500"
    : "bg-green-500 text-white border-green-500"

  return (
    <Card className={cn("bg-gradient-to-br", dirGradient)}>
      <CardContent className="space-y-4 pt-1">
        {/* Direction badge — most prominent element */}
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-bold">{stock.name}</h3>
            <span className="text-xs text-muted-foreground font-mono">
              {stock.symbol}
            </span>
          </div>
          <Badge className={cn("text-sm px-3 py-1 font-bold", dirBadge)}>
            {directionLabel}
          </Badge>
        </div>

        {/* Key metrics grid */}
        <div className="grid grid-cols-2 gap-3">
          {/* Entry price range */}
          <div className="rounded-lg bg-blue-500/10 border border-blue-500/20 p-3">
            <div className="flex items-center gap-1.5 text-xs text-blue-400 mb-1">
              <TrendingUp className="h-3 w-3" />
              {isSell ? "卖出区间" : "买入区间"}
            </div>
            <p className="font-mono font-semibold text-sm">
              ¥{formatPrice(stock.buy_range[0])} - ¥{formatPrice(stock.buy_range[1])}
            </p>
          </div>

          {/* Position size — shares + yuan */}
          <div className="rounded-lg bg-primary/10 border border-primary/20 p-3">
            <div className="flex items-center gap-1.5 text-xs text-primary mb-1">
              <Target className="h-3 w-3" />
              仓位
            </div>
            {stock.size_shares != null && stock.size_amount != null ? (
              <p className="font-mono font-semibold text-sm">
                {stock.size_shares.toLocaleString()}股{" "}
                <span className="text-xs text-muted-foreground font-normal">
                  ≈ {formatYuan(stock.size_amount)}
                </span>
              </p>
            ) : (
              <p className="font-mono font-semibold text-sm">
                {stock.position_pct}%
              </p>
            )}
          </div>

          {/* Stop loss */}
          <div className="rounded-lg bg-red-500/10 border border-red-500/20 p-3">
            <div className="flex items-center gap-1.5 text-xs text-red-400 mb-1">
              <ShieldAlert className="h-3 w-3" />
              止损价
            </div>
            <p className="font-mono font-semibold text-sm text-red-400">
              ¥{formatPrice(stock.stop_loss)}
            </p>
          </div>

          {/* Target */}
          <div className="rounded-lg bg-green-500/10 border border-green-500/20 p-3">
            <div className="flex items-center gap-1.5 text-xs text-green-400 mb-1">
              <TrendingUp className="h-3 w-3" />
              目标价
            </div>
            <p className="font-mono font-semibold text-sm text-green-400">
              ¥{formatPrice(stock.target)}
            </p>
          </div>
        </div>

        {/* Holding period */}
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Clock className="h-3 w-3" />
          持有周期：{stock.holding_days}
        </div>

        {/* Reason */}
        <div className="rounded-lg bg-card border p-3">
          <p className="text-xs text-muted-foreground mb-1 font-medium">
            {isSell ? "卖出理由" : "推荐理由"}
          </p>
          <p className="text-sm leading-relaxed">{stock.reason}</p>
        </div>

        {/* Risk notes */}
        {stock.risk_notes && stock.risk_notes.length > 0 && (
          <div className="rounded-lg bg-amber-500/5 border border-amber-500/20 p-3">
            <p className="text-xs text-amber-400 mb-1 font-medium flex items-center gap-1">
              <AlertTriangle className="h-3 w-3" />
              风险提示
            </p>
            <ul className="text-xs text-muted-foreground space-y-0.5">
              {stock.risk_notes.map((note, i) => (
                <li key={i}>• {note}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Confidence + Urgency row */}
        {(stock.confidence || stock.urgency) && (
          <div className="flex items-center gap-2 flex-wrap">
            {stock.confidence && (
              <Badge
                variant="outline"
                className={cn(
                  "text-xs border",
                  CONFIDENCE_STYLES[stock.confidence] ?? CONFIDENCE_STYLES["中"],
                )}
              >
                信心：{stock.confidence}
              </Badge>
            )}
            {stock.urgency && (
              <span className="flex items-center gap-1 text-xs text-amber-400 font-medium">
                <Clock className="h-3 w-3" />
                {stock.urgency}
              </span>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ── Late Session Layout ───────────────────────────────────────

function LateSessionLayout({ message }: { message: Message }) {
  const stocks = message.stock_recommendations ?? []

  return (
    <div className="space-y-6">
      {/* Header banner */}
      <div className="rounded-lg border border-orange-500/30 bg-gradient-to-r from-orange-500/10 via-orange-500/5 to-transparent p-4">
        <div className="flex items-center gap-2 mb-2">
          <AlertTriangle className="h-5 w-5 text-orange-400" />
          <h2 className="font-bold text-orange-400">尾盘决策建议</h2>
        </div>
        <p className="text-sm text-muted-foreground leading-relaxed">
          {message.summary}
        </p>
      </div>

      {/* Stock recommendation cards */}
      {stocks.length > 0 ? (
        <div className="space-y-4">
          <h3 className="text-sm font-semibold text-muted-foreground">
            推荐标的 ({stocks.length})
          </h3>
          {stocks.map((stock) => (
            <StockRecommendationCard key={stock.symbol} stock={stock} />
          ))}
        </div>
      ) : (
        <div className="prose prose-sm dark:prose-invert max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {message.content ?? ""}
          </ReactMarkdown>
        </div>
      )}

      {/* Disclaimer */}
      <div className="flex gap-2 rounded-lg border border-yellow-500/20 bg-yellow-500/5 p-3 text-xs text-muted-foreground">
        <AlertTriangle className="h-4 w-4 shrink-0 text-yellow-500 mt-0.5" />
        <p>
          免责声明：以上建议仅供参考，不构成投资建议。市场有风险，投资需谨慎。
          请结合自身情况做出决策。
        </p>
      </div>
    </div>
  )
}

// ── Post Market Layout ────────────────────────────────────────

function PostMarketLayout({ message }: { message: Message }) {
  const pmd = message.post_market_data

  if (!pmd) {
    return <DefaultLayout message={message} />
  }

  const isProfit = pmd.total_pnl_pct >= 0

  return (
    <div className="space-y-6">
      {/* P&L Summary */}
      <Card
        className={cn(
          "border",
          isProfit ? "border-green-500/30" : "border-red-500/30",
        )}
      >
        <CardHeader>
          <CardTitle className="text-sm text-muted-foreground">
            今日盈亏
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="flex items-baseline gap-3">
            <span
              className={cn(
                "text-3xl font-bold font-mono",
                isProfit ? "text-green-400" : "text-red-400",
              )}
            >
              {formatPct(pmd.total_pnl_pct)}
            </span>
            <span
              className={cn(
                "text-lg font-mono",
                isProfit ? "text-green-400/70" : "text-red-400/70",
              )}
            >
              {isProfit ? "+" : ""}
              {pmd.total_pnl_amount.toFixed(2)}
            </span>
          </div>
          <div className="flex items-center gap-1">
            {isProfit ? (
              <TrendingUp className="h-4 w-4 text-green-400" />
            ) : (
              <TrendingDown className="h-4 w-4 text-red-400" />
            )}
            <span className="text-xs text-muted-foreground">
              {isProfit ? "盈利" : "亏损"}
            </span>
          </div>
        </CardContent>
      </Card>

      {/* Per-stock performance table */}
      {pmd.stocks.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-muted-foreground mb-3">
            个股表现
          </h3>
          <div className="overflow-x-auto rounded-lg border">
            <table className="data-table">
              <thead>
                <tr>
                  <th className="text-left">股票</th>
                  <th data-type="numeric">买入价</th>
                  <th data-type="numeric">现价</th>
                  <th data-type="numeric">涨跌幅</th>
                  <th data-type="numeric">盈亏</th>
                </tr>
              </thead>
              <tbody>
                {pmd.stocks.map((s) => (
                  <tr key={s.symbol}>
                    <td>
                      <div>
                        <span className="font-medium">{s.name}</span>
                        <span className="ml-1.5 text-xs text-muted-foreground font-mono">
                          {s.symbol}
                        </span>
                      </div>
                    </td>
                    <td data-type="numeric" className="font-mono">
                      {formatPrice(s.entry_price)}
                    </td>
                    <td data-type="numeric" className="font-mono">
                      {formatPrice(s.current_price)}
                    </td>
                    <td
                      data-type="numeric"
                      data-pnl={
                        s.pnl_pct > 0
                          ? "positive"
                          : s.pnl_pct < 0
                            ? "negative"
                            : "zero"
                      }
                      className="font-mono"
                    >
                      {formatPct(s.pnl_pct)}
                    </td>
                    <td
                      data-type="numeric"
                      data-pnl={
                        s.pnl_amount > 0
                          ? "positive"
                          : s.pnl_amount < 0
                            ? "negative"
                            : "zero"
                      }
                      className="font-mono"
                    >
                      {s.pnl_amount >= 0 ? "+" : ""}
                      {s.pnl_amount.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Next day plan */}
      {pmd.next_day_plan && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">明日计划</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm leading-relaxed text-muted-foreground">
              {pmd.next_day_plan}
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

// ── Signal Layout (buy_signal / sell_signal with recommendations) ──

function SignalLayout({ message }: { message: Message }) {
  const stocks = message.stock_recommendations ?? []
  const isSell = message.type === "sell_signal"

  return (
    <div className="space-y-6">
      {/* Summary banner */}
      <div
        className={cn(
          "rounded-lg border p-4",
          isSell
            ? "border-red-500/30 bg-gradient-to-r from-red-500/10 via-red-500/5 to-transparent"
            : "border-green-500/30 bg-gradient-to-r from-green-500/10 via-green-500/5 to-transparent",
        )}
      >
        <div className="flex items-center gap-2 mb-2">
          {isSell ? (
            <TrendingDown className="h-5 w-5 text-red-400" />
          ) : (
            <TrendingUp className="h-5 w-5 text-green-400" />
          )}
          <h2
            className={cn(
              "font-bold",
              isSell ? "text-red-400" : "text-green-400",
            )}
          >
            {isSell ? "卖出信号" : "买入信号"}
          </h2>
        </div>
        <p className="text-sm text-muted-foreground leading-relaxed">
          {message.summary}
        </p>
      </div>

      {/* Stock executor cards */}
      {stocks.length > 0 && (
        <div className="space-y-4">
          <h3 className="text-sm font-semibold text-muted-foreground">
            {isSell ? "卖出标的" : "推荐标的"} ({stocks.length})
          </h3>
          {stocks.map((stock) => (
            <StockRecommendationCard key={stock.symbol} stock={stock} />
          ))}
        </div>
      )}

      {/* Remaining content if any */}
      {message.content && (
        <div className="prose prose-sm dark:prose-invert max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {message.content}
          </ReactMarkdown>
        </div>
      )}

      {/* Disclaimer */}
      <div className="flex gap-2 rounded-lg border border-yellow-500/20 bg-yellow-500/5 p-3 text-xs text-muted-foreground">
        <AlertTriangle className="h-4 w-4 shrink-0 text-yellow-500 mt-0.5" />
        <p>
          免责声明：以上建议仅供参考，不构成投资建议。市场有风险，投资需谨慎。
          请结合自身情况做出决策。
        </p>
      </div>
    </div>
  )
}

// ── Default Layout ────────────────────────────────────────────

function DefaultLayout({ message }: { message: Message }) {
  // For buy_signal / sell_signal with structured data, use SignalLayout
  if (
    (message.type === "buy_signal" || message.type === "sell_signal") &&
    message.stock_recommendations &&
    message.stock_recommendations.length > 0
  ) {
    return <SignalLayout message={message} />
  }

  return (
    <div className="prose prose-sm dark:prose-invert max-w-none">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {message.content ?? ""}
      </ReactMarkdown>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────

export default function MessageDetail() {
  const { messageId } = useParams<{ messageId: string }>()
  const navigate = useNavigate()
  const { data: message, isLoading } = useMessageDetail(messageId ?? null)
  const markRead = useMarkMessageRead()

  // Auto-mark as read
  useEffect(() => {
    if (message && !message.read && messageId) {
      markRead.mutate(messageId)
    }
  }, [message, messageId]) // eslint-disable-line react-hooks/exhaustive-deps

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-32" />
        <Skeleton className="h-6 w-3/4" />
        <Skeleton className="h-64 rounded-lg" />
      </div>
    )
  }

  if (!message) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <p className="text-sm text-muted-foreground">消息不存在或已被删除</p>
        <Button
          variant="outline"
          size="sm"
          className="mt-4"
          onClick={() => navigate("/messages")}
        >
          返回消息列表
        </Button>
      </div>
    )
  }

  const typeLabel = TYPE_LABELS[message.type] ?? message.type

  return (
    <div className="space-y-6">
      {/* Back button + meta */}
      <div className="space-y-3">
        <Button
          variant="ghost"
          size="sm"
          className="gap-1.5 -ml-2"
          onClick={() => navigate("/messages")}
        >
          <ArrowLeft className="h-4 w-4" />
          返回消息列表
        </Button>

        <div className="flex items-center gap-2 flex-wrap">
          <Badge
            className={cn(
              message.type === "late_session"
                ? "bg-orange-500 text-white border-orange-500"
                : message.type === "buy_signal"
                  ? "bg-green-500 text-white border-green-500"
                  : message.type === "sell_signal"
                    ? "bg-red-500 text-white border-red-500"
                    : "variant-outline",
            )}
            variant={
              message.type === "late_session" ||
              message.type === "buy_signal" ||
              message.type === "sell_signal"
                ? "default"
                : "outline"
            }
          >
            {typeLabel}
          </Badge>
          <span className="text-xs text-muted-foreground">
            {formatDateTime(message.created_at)}
          </span>
        </div>

        <h1
          className={cn(
            "font-bold leading-tight",
            message.type === "late_session" ? "text-xl" : "text-lg",
          )}
        >
          {message.title}
        </h1>
      </div>

      {/* Content — type-specific layout */}
      {message.type === "late_session" ? (
        <LateSessionLayout message={message} />
      ) : message.type === "post_market" ? (
        <PostMarketLayout message={message} />
      ) : (
        <DefaultLayout message={message} />
      )}
    </div>
  )
}
