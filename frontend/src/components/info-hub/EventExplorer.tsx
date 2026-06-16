/** Event Explorer — timeline view of clustered events with cross-verification indicators.
 *
 * v23.0 Phase 3: Displays event clusters sorted by recency with expandable item lists,
 * source count, time range, and cross-verification scoring.
 */

import { useState } from "react"
import { ChevronDown, Clock, Layers, Search } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { cn } from "@/lib/utils"
import { useEventClusters } from "@/hooks/useInfoHub"
import { CrossVerificationBadge } from "./CrossVerificationBadge"
import { ScoreBadge } from "./ScoreBadge"
import type { EventCluster } from "@/types/info-hub"
import { CATEGORY_LABELS } from "@/types/info-hub"

// ─── Filter options ──────────────────────────────────────────────────────────

const DAYS_OPTIONS = [
  { value: 1, label: "1天" },
  { value: 3, label: "3天" },
  { value: 7, label: "7天" },
]

const MIN_SOURCES_OPTIONS = [
  { value: 1, label: "1+" },
  { value: 2, label: "2+" },
  { value: 3, label: "3+" },
]

// ─── Relative time helper ────────────────────────────────────────────────────

function relativeTime(iso: string): string {
  const now = Date.now()
  const then = new Date(iso).getTime()
  const diffMs = now - then
  if (diffMs < 0) return "刚刚"

  const minutes = Math.floor(diffMs / 60000)
  if (minutes < 1) return "刚刚"
  if (minutes < 60) return `${minutes}分钟前`

  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}小时前`

  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}天前`

  const months = Math.floor(days / 30)
  return `${months}个月前`
}

// ─── Cluster card ────────────────────────────────────────────────────────────

function ClusterCard({ cluster }: { cluster: EventCluster }) {
  const [open, setOpen] = useState(false)

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div className="relative flex gap-4">
        {/* Timeline dot + line */}
        <div className="flex flex-col items-center shrink-0 pt-1">
          <div className="h-3 w-3 rounded-full border-2 border-primary bg-bg-elevated" />
          <div className="w-px flex-1 bg-border" />
        </div>

        {/* Card content */}
        <div className="flex-1 min-w-0 pb-6">
          <CollapsibleTrigger asChild>
            <div
              className={cn(
                "rounded-lg border bg-bg-elevated p-4 cursor-pointer transition-colors hover:bg-accent/50",
                open && "bg-accent/30",
              )}
            >
              {/* Header row: verification badge + source count */}
              <div className="flex items-center justify-between gap-3 mb-2">
                <CrossVerificationBadge
                  score={cluster.cross_verification_score}
                  sources={cluster.unique_sources}
                />
                <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                  <Layers className="h-3 w-3" />
                  <span>{cluster.unique_sources}个源报道</span>
                </div>
              </div>

              {/* Representative title */}
              <h3 className="text-sm font-semibold leading-snug mb-2">
                {cluster.representative_title}
              </h3>

              {/* Time range */}
              <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <Clock className="h-3 w-3 shrink-0" />
                <span>
                  最早: {relativeTime(cluster.earliest)} — 最新: {relativeTime(cluster.latest)}
                </span>
              </div>

              {/* Item count + expand indicator */}
              <div className="flex items-center justify-between mt-3">
                <span className="text-[11px] text-muted-foreground">
                  {cluster.items.length} 条相关情报
                </span>
                <ChevronDown
                  className={cn(
                    "h-4 w-4 text-muted-foreground transition-transform",
                    open && "rotate-180",
                  )}
                />
              </div>
            </div>
          </CollapsibleTrigger>

          {/* Expanded items list */}
          <CollapsibleContent>
            <div className="mt-2 space-y-1.5 pl-2">
              {cluster.items.map((item) => (
                <div
                  key={item.item_id}
                  className="rounded-md border border-border-subtle bg-bg-elevated/50 p-3 space-y-1"
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <Badge variant="secondary" className="text-[10px]">
                      {CATEGORY_LABELS[item.category] ?? item.category}
                    </Badge>
                    <ScoreBadge score={item.content_score} explain={item.score_explain} />
                    <span className="text-[10px] text-muted-foreground">{item.source_name}</span>
                  </div>
                  <h4 className="text-xs font-medium leading-snug line-clamp-2">{item.title}</h4>
                  <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                    {item.published_at && <span>{relativeTime(item.published_at)}</span>}
                    {item.url && (
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-primary hover:underline"
                        onClick={(e) => e.stopPropagation()}
                      >
                        查看原文
                      </a>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </CollapsibleContent>
        </div>
      </div>
    </Collapsible>
  )
}

// ─── Main component ──────────────────────────────────────────────────────────

export function EventExplorer() {
  const [days, setDays] = useState(7)
  const [minSources, setMinSources] = useState(1)
  const { data, isLoading, error } = useEventClusters(days, minSources)

  const clusters = data?.clusters ?? []

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <Search className="h-4 w-4 text-primary" />
          <h2 className="text-base font-semibold">事件探索</h2>
        </div>

        {/* Filter controls */}
        <div className="flex items-center gap-4">
          {/* Days selector */}
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] text-muted-foreground">时间:</span>
            <div className="flex gap-1">
              {DAYS_OPTIONS.map((opt) => (
                <Button
                  key={opt.value}
                  variant={days === opt.value ? "default" : "outline"}
                  size="xs"
                  onClick={() => setDays(opt.value)}
                >
                  {opt.label}
                </Button>
              ))}
            </div>
          </div>

          {/* Min sources selector */}
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] text-muted-foreground">最少源:</span>
            <div className="flex gap-1">
              {MIN_SOURCES_OPTIONS.map((opt) => (
                <Button
                  key={opt.value}
                  variant={minSources === opt.value ? "default" : "outline"}
                  size="xs"
                  onClick={() => setMinSources(opt.value)}
                >
                  {opt.label}
                </Button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Loading state */}
      {isLoading && (
        <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
          加载事件聚类数据...
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="flex items-center justify-center py-12 text-sm text-red-400">
          加载失败: {error instanceof Error ? error.message : "未知错误"}
        </div>
      )}

      {/* Empty state */}
      {!isLoading && !error && clusters.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 text-sm text-muted-foreground gap-2">
          <Layers className="h-8 w-8 text-muted-foreground/40" />
          <span>暂无事件聚类数据</span>
        </div>
      )}

      {/* Timeline */}
      {clusters.length > 0 && (
        <div className="space-y-0">
          {clusters.map((cluster) => (
            <ClusterCard key={cluster.cluster_id} cluster={cluster} />
          ))}
        </div>
      )}
    </div>
  )
}
