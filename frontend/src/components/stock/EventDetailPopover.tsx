import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Badge } from "@/components/ui/badge"
import { X, Newspaper, Crown, TrendingUp, AlertTriangle } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { ChartEvent } from "@/types/analysis"

/** Event type display config */
const EVENT_TYPE_CONFIG: Record<
  ChartEvent["type"],
  { label: string; color: string; bg: string; icon: React.ReactNode }
> = {
  news: {
    label: "\u65B0\u95FB",        // 新闻
    color: "#3b82f6",
    bg: "rgba(59, 130, 246, 0.1)",
    icon: <Newspaper className="h-3.5 w-3.5" />,
  },
  dragon_tiger: {
    label: "\u9F99\u864E\u699C",  // 龙虎榜
    color: "#f59e0b",
    bg: "rgba(245, 158, 11, 0.1)",
    icon: <Crown className="h-3.5 w-3.5" />,
  },
  pattern: {
    label: "\u5F62\u6001",        // 形态
    color: "#8b5cf6",
    bg: "rgba(139, 92, 246, 0.1)",
    icon: <TrendingUp className="h-3.5 w-3.5" />,
  },
  anomaly: {
    label: "\u5F02\u52A8",        // 异动
    color: "#ef4444",
    bg: "rgba(239, 68, 68, 0.1)",
    icon: <AlertTriangle className="h-3.5 w-3.5" />,
  },
}

/** Impact color mapping (A-share convention: positive = red, negative = green) */
const IMPACT_CONFIG: Record<
  ChartEvent["impact"],
  { label: string; color: string }
> = {
  positive: { label: "\u5229\u597D", color: "var(--color-market-up)" },   // 利好
  negative: { label: "\u5229\u7A7A", color: "var(--color-market-down)" },   // 利空
  neutral:  { label: "\u4E2D\u6027", color: "var(--color-market-flat)" },   // 中性
}

interface EventDetailPopoverProps {
  event: ChartEvent
  onClose: () => void
  children: React.ReactNode
}

export function EventDetailPopover({ event, onClose, children }: EventDetailPopoverProps) {
  const typeConfig = EVENT_TYPE_CONFIG[event.type]
  const impactConfig = IMPACT_CONFIG[event.impact]

  return (
    <Popover open onOpenChange={(open) => { if (!open) onClose() }}>
      <PopoverTrigger asChild>
        {children}
      </PopoverTrigger>
      <PopoverContent className="w-80 p-0" align="start">
        <div className="p-4 space-y-3">
          {/* Header: close button */}
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2 flex-wrap">
              <Badge
                className="gap-1 text-xs"
                style={{ backgroundColor: typeConfig.bg, color: typeConfig.color, borderColor: typeConfig.color }}
                variant="outline"
              >
                {typeConfig.icon}
                {typeConfig.label}
              </Badge>
              <Badge
                className="text-xs"
                style={{ backgroundColor: "transparent", color: impactConfig.color, borderColor: impactConfig.color }}
                variant="outline"
              >
                {impactConfig.label}
              </Badge>
            </div>
            <Button variant="ghost" size="sm" className="h-6 w-6 p-0 shrink-0" onClick={onClose}>
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>

          {/* Title */}
          <p className="text-sm font-medium leading-snug">{event.title}</p>

          {/* Date */}
          <p className="text-xs text-muted-foreground font-mono">{event.date}</p>

          {/* Details */}
          {event.details && (
            <div className="border-t pt-2">
              <p className="text-xs text-muted-foreground leading-relaxed">{event.details}</p>
            </div>
          )}
        </div>
      </PopoverContent>
    </Popover>
  )
}

/** Standalone version that can be rendered without a trigger (used inline) */
interface EventDetailInlineProps {
  event: ChartEvent
}

export function EventDetailInline({ event }: EventDetailInlineProps) {
  const typeConfig = EVENT_TYPE_CONFIG[event.type]
  const impactConfig = IMPACT_CONFIG[event.impact]

  return (
    <div className="rounded-lg border p-3 space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <Badge
          className="gap-1 text-xs"
          style={{ backgroundColor: typeConfig.bg, color: typeConfig.color, borderColor: typeConfig.color }}
          variant="outline"
        >
          {typeConfig.icon}
          {typeConfig.label}
        </Badge>
        <Badge
          className="text-xs"
          style={{ backgroundColor: "transparent", color: impactConfig.color, borderColor: impactConfig.color }}
          variant="outline"
        >
          {impactConfig.label}
        </Badge>
        <span className="text-[10px] text-muted-foreground font-mono ml-auto">{event.date}</span>
      </div>
      <p className="text-sm font-medium leading-snug">{event.title}</p>
      {event.details && (
        <p className="text-xs text-muted-foreground leading-relaxed">{event.details}</p>
      )}
    </div>
  )
}
