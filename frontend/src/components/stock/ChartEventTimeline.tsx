import { useState } from "react"
import { ChevronDown, ChevronUp, ExternalLink } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import type { ChartEvent } from "@/types/analysis"

const EVENT_TYPE_CONFIG: Record<
  ChartEvent["type"],
  { label: string; color: string; shape: string }
> = {
  news:         { label: "新闻",   color: "#3b82f6", shape: "●" },
  dragon_tiger: { label: "龙虎榜", color: "#f97316", shape: "▲" },
  pattern:      { label: "形态",   color: "#a855f7", shape: "■" },
  anomaly:      { label: "异动",   color: "#eab308", shape: "▼" },
}

const IMPACT_COLOR: Record<string, string> = {
  positive: "var(--color-market-up)",
  negative: "var(--color-market-down)",
  neutral: "var(--color-market-flat)",
}

const IMPACT_LABEL: Record<string, string> = {
  positive: "利好",
  negative: "利空",
  neutral: "中性",
}

const DEFAULT_VISIBLE = 5

interface ChartEventTimelineProps {
  events: ChartEvent[]
}

export function ChartEventTimeline({ events }: ChartEventTimelineProps) {
  const [expanded, setExpanded] = useState(false)

  if (!events || events.length === 0) return null

  // Sort by date descending (most recent first)
  const sorted = [...events].sort((a, b) => b.date.localeCompare(a.date))
  const visible = expanded ? sorted : sorted.slice(0, DEFAULT_VISIBLE)
  const hasMore = sorted.length > DEFAULT_VISIBLE

  return (
    <div className="rounded-lg border bg-card">
      {/* Legend bar */}
      <div className="flex items-center gap-4 px-4 py-2 border-b">
        <span className="text-xs font-medium text-muted-foreground">事件标注</span>
        <div className="flex items-center gap-3 ml-auto">
          {Object.entries(EVENT_TYPE_CONFIG).map(([key, cfg]) => (
            <span key={key} className="flex items-center gap-1 text-[11px] text-muted-foreground">
              <span style={{ color: cfg.color }}>{cfg.shape}</span>
              {cfg.label}
            </span>
          ))}
        </div>
      </div>

      {/* Event list */}
      <div className="divide-y">
        {visible.map((event, idx) => {
          const typeCfg = EVENT_TYPE_CONFIG[event.type]
          const impactColor = IMPACT_COLOR[event.impact] ?? IMPACT_COLOR.neutral
          const impactLabel = IMPACT_LABEL[event.impact] ?? "中性"

          return (
            <div key={`${event.date}-${idx}`} className="flex items-start gap-3 px-4 py-2">
              {/* Colored dot */}
              <span
                className="mt-1 shrink-0 h-2 w-2 rounded-full"
                style={{ backgroundColor: typeCfg.color }}
              />
              {/* Date */}
              <span className="text-[11px] font-numeric text-muted-foreground shrink-0 w-20 mt-0.5">
                {event.date}
              </span>
              {/* Title — clickable for news/anomaly with url */}
              <span className="text-xs leading-snug flex-1 min-w-0">
                {event.url ? (
                  <a
                    href={event.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:underline inline-flex items-center gap-1"
                    style={{ color: typeCfg.color }}
                  >
                    {event.title}
                    <ExternalLink className="h-2.5 w-2.5 shrink-0 opacity-60" />
                  </a>
                ) : (
                  event.title
                )}
              </span>
              {/* Impact badge */}
              <Badge
                variant="outline"
                className="text-[10px] shrink-0 px-1.5 py-0"
                style={{ color: impactColor, borderColor: impactColor }}
              >
                {impactLabel}
              </Badge>
            </div>
          )
        })}
      </div>

      {/* Expand/collapse */}
      {hasMore && (
        <div className="flex justify-center py-1.5 border-t">
          <Button
            variant="ghost"
            size="sm"
            className="h-6 text-xs text-muted-foreground gap-1"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? (
              <>收起 <ChevronUp className="h-3 w-3" /></>
            ) : (
              <>查看全部 {sorted.length} 条 <ChevronDown className="h-3 w-3" /></>
            )}
          </Button>
        </div>
      )}
    </div>
  )
}
