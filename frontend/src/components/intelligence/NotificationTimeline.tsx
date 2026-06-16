/** Notification timeline — grouped by trading phase. */

import { useMemo } from "react"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useTimeline } from "@/hooks/useMarketIntelligence"
import type { TimelineEntry } from "@/types/intelligence"
import { SIGNAL_TYPE_LABELS, RISK_LEVEL_LABELS, MARKET_PHASE_LABELS } from "@/types/intelligence"
import { Clock } from "lucide-react"

const RISK_COLORS: Record<string, string> = {
  LOW: "text-green-500",
  MODERATE: "text-yellow-500",
  ELEVATED: "text-orange-500",
  EXTREME: "text-red-500",
}

export function NotificationTimeline() {
  const { data: entries, isLoading } = useTimeline({ limit: 100, days: 3 })

  const grouped = useMemo(() => {
    if (!entries || entries.length === 0) return []

    const groups: Map<string, TimelineEntry[]> = new Map()
    for (const entry of entries) {
      const dateKey = new Date(entry.timestamp).toLocaleDateString("zh-CN")
      const phaseKey = `${dateKey} — ${MARKET_PHASE_LABELS[entry.phase] ?? entry.phase}`
      if (!groups.has(phaseKey)) groups.set(phaseKey, [])
      groups.get(phaseKey)!.push(entry)
    }

    return Array.from(groups.entries()).map(([label, items]) => ({
      label,
      items: items.sort(
        (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
      ),
    }))
  }, [entries])

  if (isLoading) {
    return (
      <div className="space-y-4">
        {[1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-20 w-full rounded-lg" />
        ))}
      </div>
    )
  }

  if (grouped.length === 0) {
    return (
      <div className="py-12 text-center text-sm text-muted-foreground">
        暂无通知记录
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {grouped.map((group) => (
        <div key={group.label}>
          <div className="flex items-center gap-2 mb-3">
            <Clock className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="text-xs font-medium text-muted-foreground">{group.label}</span>
            <Badge variant="outline" className="text-[10px]">
              {group.items.length}
            </Badge>
          </div>

          <div className="space-y-2 border-l-2 border-muted pl-4">
            {group.items.map((entry) => (
              <TimelineItem key={entry.signal_id} entry={entry} />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function TimelineItem({ entry }: { entry: TimelineEntry }) {
  const typeLabel = SIGNAL_TYPE_LABELS[entry.signal_type] ?? entry.signal_type
  const riskColor = RISK_COLORS[entry.risk_level] ?? ""

  return (
    <Card className="hover:bg-muted/30 transition-colors">
      <CardContent className="py-2.5 px-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <Badge variant="secondary" className="text-[10px] shrink-0">
              {typeLabel}
            </Badge>
            <span className="text-sm truncate">{entry.summary_short}</span>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <span className={`text-[10px] font-medium ${riskColor}`}>
              {RISK_LEVEL_LABELS[entry.risk_level]}
            </span>
            <span className="text-[10px] text-muted-foreground font-numeric">
              {new Date(entry.timestamp).toLocaleTimeString("zh-CN", {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </span>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
