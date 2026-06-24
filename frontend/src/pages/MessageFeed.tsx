/** MessageFeed page — quant trading schedule message feed.
 *
 * Shows time-ordered messages from the quant agent pipeline with
 * filter tabs by category. Late session (尾盘决策) messages are
 * visually prominent as the most important decision point.
 *
 * Per PRD v37.0 Quant Agent Schedule.
 */

import { useState } from "react"
import { useNavigate } from "react-router-dom"
import {
  MessageSquare,
  Clock,
  Sun,
  BarChart3,
  Moon,
  Palmtree,
  AlertTriangle,
  TrendingUp,
  TrendingDown,
  Eye,
  Bell,
  Globe,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useMessages } from "@/hooks/useMessages"
import { cn } from "@/lib/utils"
import type { Message, MessageType } from "@/types/message"
import type { LucideIcon } from "lucide-react"

// ── Type configs ──────────────────────────────────────────────

interface TypeConfig {
  label: string
  color: string
  bgColor: string
  borderColor: string
  icon: LucideIcon
}

const MESSAGE_TYPE_CONFIG: Record<MessageType, TypeConfig> = {
  buy_signal: {
    label: "买入信号",
    color: "text-green-500",
    bgColor: "bg-green-500/10",
    borderColor: "border-green-500/20",
    icon: TrendingUp,
  },
  sell_signal: {
    label: "卖出信号",
    color: "text-red-500",
    bgColor: "bg-red-500/10",
    borderColor: "border-red-500/20",
    icon: TrendingDown,
  },
  risk_alert: {
    label: "风险提醒",
    color: "text-amber-500",
    bgColor: "bg-amber-500/10",
    borderColor: "border-amber-500/20",
    icon: AlertTriangle,
  },
  market_watch: {
    label: "市场观察",
    color: "text-blue-400",
    bgColor: "bg-blue-400/10",
    borderColor: "border-blue-400/20",
    icon: Eye,
  },
  hold_reminder: {
    label: "持仓提醒",
    color: "text-gray-400",
    bgColor: "bg-gray-400/10",
    borderColor: "border-gray-400/20",
    icon: Bell,
  },
  // v37.0 quant schedule types
  pre_market: {
    label: "盘前分析",
    color: "text-blue-400",
    bgColor: "bg-blue-400/10",
    borderColor: "border-blue-400/20",
    icon: Sun,
  },
  call_auction: {
    label: "集合竞价",
    color: "text-cyan-400",
    bgColor: "bg-cyan-400/10",
    borderColor: "border-cyan-400/20",
    icon: Clock,
  },
  intraday_signal: {
    label: "盘中信号",
    color: "text-green-400",
    bgColor: "bg-green-400/10",
    borderColor: "border-green-400/20",
    icon: BarChart3,
  },
  late_session: {
    label: "尾盘决策",
    color: "text-orange-400",
    bgColor: "bg-orange-500/15",
    borderColor: "border-orange-500/30",
    icon: AlertTriangle,
  },
  post_market: {
    label: "盘后复盘",
    color: "text-purple-400",
    bgColor: "bg-purple-400/10",
    borderColor: "border-purple-400/20",
    icon: Moon,
  },
  holiday_intel: {
    label: "假期情报",
    color: "text-teal-400",
    bgColor: "bg-teal-400/10",
    borderColor: "border-teal-400/20",
    icon: Palmtree,
  },
  global_intelligence: {
    label: "全球情报",
    color: "text-indigo-400",
    bgColor: "bg-indigo-400/10",
    borderColor: "border-indigo-400/20",
    icon: Globe,
  },
  intelligence_digest: {
    label: "情报摘要",
    color: "text-indigo-400",
    bgColor: "bg-indigo-400/10",
    borderColor: "border-indigo-400/20",
    icon: Globe,
  },
  global_pulse: {
    label: "全球脉搏",
    color: "text-indigo-400",
    bgColor: "bg-indigo-400/10",
    borderColor: "border-indigo-400/20",
    icon: Globe,
  },
  market_pulse: {
    label: "市场脉搏",
    color: "text-cyan-400",
    bgColor: "bg-cyan-400/10",
    borderColor: "border-cyan-400/20",
    icon: TrendingUp,
  },
}

// ── Filter categories ─────────────────────────────────────────

interface FilterTab {
  key: string
  label: string
  types: MessageType[]
}

const FILTER_TABS: FilterTab[] = [
  { key: "all", label: "全部", types: [] },
  {
    key: "trade",
    label: "买卖建议",
    types: ["buy_signal", "sell_signal"],
  },
  {
    key: "intraday",
    label: "盘中",
    types: ["pre_market", "call_auction", "intraday_signal"],
  },
  {
    key: "late",
    label: "尾盘决策",
    types: ["late_session"],
  },
  {
    key: "review",
    label: "复盘",
    types: ["post_market"],
  },
  {
    key: "holiday",
    label: "假期",
    types: ["holiday_intel"],
  },
]

// ── Helper ────────────────────────────────────────────────────

function formatTime(dateStr: string): string {
  const d = new Date(dateStr)
  const now = new Date()
  const isToday =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()

  if (isToday) {
    return d.toLocaleTimeString("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
    })
  }
  return d.toLocaleDateString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

// ── Message card ──────────────────────────────────────────────

function MessageCard({
  message,
  onClick,
}: {
  message: Message
  onClick: (msg: Message) => void
}) {
  const config = MESSAGE_TYPE_CONFIG[message.type] ?? MESSAGE_TYPE_CONFIG.market_watch
  const isLateSession = message.type === "late_session"
  const isSignalType = message.type === "buy_signal" || message.type === "sell_signal"
  const Icon = config.icon

  return (
    <Card
      className={cn(
        "cursor-pointer transition-all duration-200 hover:border-border-strong",
        "relative overflow-hidden",
        isLateSession && [
          "border-orange-500/40",
          "bg-gradient-to-r from-orange-500/5 via-card to-card",
          "shadow-[0_0_12px_rgba(249,115,22,0.08)]",
          "py-6",
        ],
        !isLateSession && "py-4",
        !message.read && "border-l-2 border-l-primary",
      )}
      onClick={() => onClick(message)}
    >
      <div className={cn("px-5", isLateSession ? "space-y-3" : "space-y-2")}>
        {/* Header row */}
        <div className="flex items-center gap-2">
          <div
            className={cn(
              "flex items-center justify-center rounded-md",
              isLateSession
                ? "h-8 w-8 bg-orange-500/20"
                : "h-6 w-6",
              config.bgColor,
            )}
          >
            <Icon
              className={cn(
                config.color,
                isLateSession ? "h-4.5 w-4.5" : "h-3.5 w-3.5",
              )}
            />
          </div>

          <Badge
            className={cn(
              isLateSession
                ? "bg-orange-500 text-white border-orange-500 text-xs px-2 py-0.5"
                : cn(config.bgColor, config.color, config.borderColor, "border"),
            )}
          >
            {config.label}
          </Badge>

          {message.priority === "high" && !isLateSession && (
            <Badge variant="destructive" className="text-[10px] px-1">
              重要
            </Badge>
          )}

          <span className="ml-auto text-xs text-muted-foreground">
            {formatTime(message.created_at)}
          </span>
        </div>

        {/* Title */}
        <h3
          className={cn(
            "font-semibold leading-snug",
            isLateSession ? "text-base" : "text-sm",
            !message.read && "text-foreground",
            message.read && "text-muted-foreground",
          )}
        >
          {message.title}
        </h3>

        {/* Summary */}
        <p
          className={cn(
            "text-muted-foreground leading-relaxed line-clamp-2",
            isLateSession ? "text-sm" : "text-xs",
          )}
        >
          {message.summary}
        </p>

        {/* Late session stock count hint */}
        {isLateSession && message.stock_recommendations && (
          <div className="flex items-center gap-1.5 text-xs text-orange-400">
            <TrendingUp className="h-3.5 w-3.5" />
            <span>
              {message.stock_recommendations.length} 只推荐股票，点击查看详情
            </span>
          </div>
        )}

        {/* Buy/Sell signal preview */}
        {isSignalType &&
          message.stock_recommendations &&
          message.stock_recommendations.length > 0 && (() => {
            const first = message.stock_recommendations[0]
            const isSell = message.type === "sell_signal"
            return (
              <div className="flex items-center gap-2 flex-wrap">
                <Badge
                  className={cn(
                    "text-[10px] font-bold px-1.5 py-0",
                    isSell
                      ? "bg-red-500 text-white border-red-500"
                      : "bg-green-500 text-white border-green-500",
                  )}
                >
                  {first.direction === "SELL" ? "SELL" : "BUY"}
                </Badge>
                <span className="text-xs font-medium">
                  {first.name}
                </span>
                <span className="text-xs font-mono text-muted-foreground">
                  ¥{first.buy_range[0].toFixed(2)} - ¥{first.buy_range[1].toFixed(2)}
                </span>
                {message.stock_recommendations.length > 1 && (
                  <span className="text-xs text-muted-foreground">
                    +{message.stock_recommendations.length - 1}
                  </span>
                )}
                {first.urgency && (
                  <span className="flex items-center gap-0.5 text-[10px] text-amber-400 font-medium">
                    <Clock className="h-2.5 w-2.5" />
                    {first.urgency}
                  </span>
                )}
              </div>
            )
          })()}
      </div>
    </Card>
  )
}

// ── Main page ─────────────────────────────────────────────────

export default function MessageFeed() {
  const [activeFilter, setActiveFilter] = useState("all")
  const navigate = useNavigate()

  const currentTab = FILTER_TABS.find((t) => t.key === activeFilter)
  const filterType =
    currentTab && currentTab.types.length > 0
      ? currentTab.types.join(",")
      : undefined

  const { data, isLoading } = useMessages({ filter: filterType })

  const messages = data?.items ?? []

  const handleMessageClick = (msg: Message) => {
    navigate(`/messages/${msg.id}`)
  }

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center gap-2">
        <MessageSquare className="h-5 w-5 text-primary" />
        <h1 className="text-lg font-bold">消息中心</h1>
        {data && data.unread_count > 0 && (
          <Badge variant="default" className="text-[10px]">
            {data.unread_count} 未读
          </Badge>
        )}
      </div>

      {/* Filter tabs */}
      <div className="flex items-center gap-1 overflow-x-auto rounded-lg border p-1">
        {FILTER_TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveFilter(tab.key)}
            className={cn(
              "shrink-0 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              activeFilter === tab.key
                ? tab.key === "late"
                  ? "bg-orange-500 text-white"
                  : "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-accent hover:text-foreground",
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Message list */}
      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-28 rounded-lg" />
          ))}
        </div>
      ) : messages.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <MessageSquare className="h-10 w-10 text-muted-foreground/40 mb-3" />
          <p className="text-sm text-muted-foreground">
            暂无消息，系统将在交易时段自动推送
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {messages.map((msg) => (
            <MessageCard
              key={msg.id}
              message={msg}
              onClick={handleMessageClick}
            />
          ))}
        </div>
      )}
    </div>
  )
}
