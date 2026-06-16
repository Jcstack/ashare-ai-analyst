import { useState, useRef } from "react"
import { useNavigate } from "react-router-dom"
import { formatTime } from "@/lib/formatters"
import { useQueryClient } from "@tanstack/react-query"
import { Bell, AlertTriangle, TrendingUp, Newspaper, BarChart3, Clock, CalendarDays } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { useNotifications, useUnreadCount, useMarkAllRead, usePurgeRead } from "@/hooks/useNotifications"
import type { NotificationItem } from "@/hooks/useNotifications"
import { useInfoHubStore } from "@/stores/infoHubStore"

const TYPE_CONFIG: Record<string, { icon: typeof Bell; color: string; label: string }> = {
  anomaly: { icon: AlertTriangle, color: "#f59e0b", label: "异动" },
  sentiment_shift: { icon: TrendingUp, color: "var(--color-market-up)", label: "情绪" },
  hot_entry: { icon: BarChart3, color: "#8b5cf6", label: "热榜" },
  market_overview: { icon: Newspaper, color: "#3b82f6", label: "概览" },
  strategy_signal: { icon: TrendingUp, color: "#6366f1", label: "策略" },
  system: { icon: Bell, color: "#6b7280", label: "系统" },
  market_status: { icon: Clock, color: "#22c55e", label: "市场" },
  holiday_preview: { icon: CalendarDays, color: "#f59e0b", label: "休市" },
  intel_report: { icon: BarChart3, color: "#10b981", label: "分析" },
}


function NotificationRow({ item, onNavigate }: { item: NotificationItem; onNavigate: (item: NotificationItem) => void }) {
  const config = TYPE_CONFIG[item.type] ?? TYPE_CONFIG.anomaly
  const Icon = config.icon
  const clickable = !!item.action || !!item.symbol

  return (
    <div
      className={`flex items-start gap-2.5 p-2.5 rounded-lg transition-colors ${item.read ? "opacity-60" : "bg-accent/50"} ${clickable ? "cursor-pointer hover:bg-accent" : ""}`}
      onClick={clickable ? () => onNavigate(item) : undefined}
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
      onKeyDown={clickable ? (e) => { if (e.key === "Enter") onNavigate(item) } : undefined}
    >
      <div
        className="mt-0.5 rounded-full p-1.5 shrink-0"
        style={{ backgroundColor: config.color + "20" }}
      >
        <Icon className="h-3 w-3" style={{ color: config.color }} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium truncate">{item.title}</span>
          <Badge variant="secondary" className="text-[9px] shrink-0">{config.label}</Badge>
          {item.symbol && (
            <Badge variant="outline" className="text-[9px] shrink-0 px-1 py-0">{item.symbol}</Badge>
          )}
        </div>
        <p className="text-[11px] text-muted-foreground leading-relaxed mt-0.5 line-clamp-2">
          {item.summary}
        </p>
        <span className="text-[10px] text-muted-foreground mt-1 block">{formatTime(item.timestamp)}</span>
      </div>
    </div>
  )
}

/** Map route prefixes to React Query key prefixes to clear on navigation. */
const ROUTE_QUERY_MAP: [string, string[]][] = [
  ["/info-hub", ["info-hub"]],
  ["/reports", ["intel-reports", "intel-reports-unread"]],
  ["/market", ["market-indices", "realtime-quotes", "capital-flow"]],
  ["/portfolio", ["watchlist", "trading-profile"]],
  ["/", ["market-indices", "capital-flow"]],
]

export function NotificationCenter() {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { data: notifications } = useNotifications()
  const { data: unreadCount } = useUnreadCount()
  const markAllRead = useMarkAllRead()
  const purgeRead = usePurgeRead()
  const didMarkReadRef = useRef(false)

  const handleOpen = (isOpen: boolean) => {
    if (!isOpen && didMarkReadRef.current) {
      // Popover closing and we marked items as read during this session
      purgeRead.mutate()
      didMarkReadRef.current = false
    }
    setOpen(isOpen)
    if (isOpen) {
      // Mark all as read when popover opens (optimistic + server sync)
      const hasUnread = notifications?.some((n) => !n.read) ?? false
      if (hasUnread) {
        markAllRead.mutate()
        didMarkReadRef.current = true
      }
    }
  }

  const handleNavigate = (item: NotificationItem) => {
    setOpen(false)
    const target = item.action || (item.symbol ? `/stock/${item.symbol}` : null)
    if (!target) return

    // Remove cached queries for the target page so it does a clean fetch
    // (invalidateQueries only marks stale — inactive queries still show old data on mount)
    const basePath = target.split("?")[0]
    for (const [prefix, keys] of ROUTE_QUERY_MAP) {
      if (basePath === "/" ? prefix === "/" : basePath.startsWith(prefix) && prefix !== "/") {
        for (const key of keys) {
          queryClient.removeQueries({ queryKey: [key] })
        }
        break
      }
    }
    // Stock detail pages — remove symbol-specific queries
    if (item.symbol) {
      queryClient.removeQueries({ queryKey: ["stock", item.symbol] })
      queryClient.removeQueries({ queryKey: ["unified-analysis", item.symbol] })
    }

    // Set "新" badge IDs when navigating to info-hub from an intel notification
    if (item.new_item_ids?.length && basePath === "/info-hub") {
      useInfoHubStore.getState().setNewItemIds(new Set(item.new_item_ids))
      setTimeout(() => useInfoHubStore.getState().clearNewItemIds(), 5 * 60 * 1000)
    }

    navigate(target)
  }

  return (
    <Popover open={open} onOpenChange={handleOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon" className="relative text-muted-foreground">
          <Bell className="h-5 w-5" />
          {(unreadCount ?? 0) > 0 && (
            <span className="absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger text-[9px] text-white px-1">
              {unreadCount! > 99 ? "99+" : unreadCount}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-0">
        <div className="px-3 py-2 border-b">
          <span className="text-sm font-medium">通知中心</span>
        </div>
        <div className="max-h-80 overflow-y-auto p-1.5 space-y-1">
          {notifications && notifications.length > 0 ? (
            notifications.slice(0, 20).map((item) => (
              <NotificationRow key={item.id} item={item} onNavigate={handleNavigate} />
            ))
          ) : (
            <div className="py-8 text-center text-xs text-muted-foreground">
              暂无通知
            </div>
          )}
        </div>
      </PopoverContent>
    </Popover>
  )
}
