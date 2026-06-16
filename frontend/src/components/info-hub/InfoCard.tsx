/** Info item card — displays a single information item with expand/collapse detail view. */

import { Bookmark, ExternalLink, ChevronDown, MessageSquareShare } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { cn } from "@/lib/utils"
import { CATEGORY_LABELS, PRIORITY_COLORS, PRIORITY_LABELS } from "@/types/info-hub"
import type { InfoItem } from "@/types/info-hub"
import { ScoreBadge } from "./ScoreBadge"

interface InfoCardProps {
  item: InfoItem
  expanded: boolean
  onToggleExpand: (itemId: string) => void
  onBookmark: (itemId: string) => void
  onRead: (itemId: string) => void
  /** Multi-select mode */
  selectable?: boolean
  selected?: boolean
  onSelect?: (itemId: string) => void
  selectDisabled?: boolean
  /** Map of tracked symbol codes → names (watchlist + portfolio) for relevance matching. */
  trackedSymbols?: Map<string, string>
  /** Whether this item is newly fetched from the latest refresh. */
  isNew?: boolean
}

export function InfoCard({
  item,
  expanded,
  onToggleExpand,
  onBookmark,
  onRead,
  selectable,
  selected,
  onSelect,
  selectDisabled,
  trackedSymbols,
  isNew,
}: InfoCardProps) {
  const handleCardClick = () => {
    if (!item.is_read) onRead(item.item_id)
    onToggleExpand(item.item_id)
  }

  const redditExtra = item.extra as
    | { score?: number; num_comments?: number; subreddit?: string }
    | undefined

  // Split related_symbols into tracked (portfolio/watchlist match) vs other
  const tracked = trackedSymbols ?? new Map<string, string>()
  const nameMap = item.related_symbol_names ?? {}
  const matchedSymbols = item.related_symbols.filter((s) => tracked.has(s))
  const otherSymbols = item.related_symbols.filter((s) => !tracked.has(s))
  const resolveName = (code: string) => tracked.get(code) ?? nameMap[code] ?? code

  return (
    <div
      className={cn(
        "group rounded-lg border transition-colors",
        !item.is_read && "border-l-2 border-l-primary",
        expanded ? "bg-accent/30" : "hover:bg-accent/50",
      )}
    >
      {/* Collapsed header — always visible */}
      <div className="flex items-start gap-3 p-4 cursor-pointer" onClick={handleCardClick}>
        {/* Checkbox for multi-select */}
        {selectable && (
          <div className="pt-0.5 shrink-0" onClick={(e) => e.stopPropagation()}>
            <Checkbox
              checked={selected}
              disabled={selectDisabled && !selected}
              onCheckedChange={() => onSelect?.(item.item_id)}
            />
          </div>
        )}

        <div className="flex-1 min-w-0 space-y-1.5">
          {/* Category + priority + source */}
          <div className="flex items-center gap-2 flex-wrap">
            {isNew && (
              <Badge className="text-[10px] bg-green-500/15 text-green-600 border-green-500/30">
                新
              </Badge>
            )}
            <Badge variant="secondary" className="text-[10px]">
              {CATEGORY_LABELS[item.category] ?? item.category}
            </Badge>
            {item.priority !== "normal" && (
              <span className={cn("text-[10px] font-medium", PRIORITY_COLORS[item.priority])}>
                {PRIORITY_LABELS[item.priority]}
              </span>
            )}
            <ScoreBadge score={item.content_score} explain={item.score_explain} />
            <span className="text-[10px] text-muted-foreground">{item.source_name}</span>
          </div>

          {/* Title */}
          <h3 className="text-sm font-medium leading-snug line-clamp-2">{item.title}</h3>

          {/* Summary (truncated when collapsed) */}
          {item.summary && !expanded && (
            <p className="text-xs text-muted-foreground line-clamp-2">{item.summary}</p>
          )}

          {/* Footer: time + related symbols (tracked stocks highlighted) */}
          {!expanded && (
            <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
              {item.published_at && <span>{item.published_at}</span>}
              {item.related_symbols.length > 0 && (
                <span className="flex gap-1 flex-wrap">
                  {matchedSymbols.slice(0, 3).map((s) => (
                    <Badge key={s} className="text-[10px] px-1 py-0 bg-primary/15 text-primary border-primary/30">
                      {resolveName(s)}
                    </Badge>
                  ))}
                  {otherSymbols.slice(0, Math.max(0, 3 - matchedSymbols.length)).map((s) => (
                    <Badge key={s} variant="outline" className="text-[10px] px-1 py-0">
                      {resolveName(s)}
                    </Badge>
                  ))}
                </span>
              )}
            </div>
          )}
        </div>

        {/* Actions + expand indicator */}
        <div className="flex flex-col items-center gap-1 shrink-0">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={(e) => {
              e.stopPropagation()
              onBookmark(item.item_id)
            }}
          >
            <Bookmark
              className={cn("h-3.5 w-3.5", item.is_bookmarked && "fill-current text-primary")}
            />
          </Button>
          <ChevronDown
            className={cn(
              "h-3 w-3 text-muted-foreground transition-transform",
              expanded && "rotate-180",
            )}
          />
        </div>
      </div>

      {/* Expanded detail area */}
      {expanded && (
        <div className="border-t border-border-subtle px-4 pb-4 pt-3 space-y-3">
          {/* Full summary */}
          {item.summary && (
            <p className="text-xs text-text-secondary leading-relaxed">{item.summary}</p>
          )}

          {/* Reddit-specific metadata */}
          {redditExtra?.subreddit && (
            <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
              <span>r/{redditExtra.subreddit}</span>
              {redditExtra.score != null && <span>score: {redditExtra.score}</span>}
              {redditExtra.num_comments != null && (
                <span>{redditExtra.num_comments} comments</span>
              )}
            </div>
          )}

          {/* Metadata row */}
          <div className="flex items-center gap-3 text-[10px] text-muted-foreground flex-wrap">
            <span>
              来源: {item.source_name}
            </span>
            {item.published_at && <span>{item.published_at}</span>}
            {item.related_symbols.length > 0 && (
              <span className="flex gap-1 flex-wrap">
                {matchedSymbols.map((s) => (
                  <Badge key={s} className="text-[10px] px-1.5 py-0 bg-primary/15 text-primary border-primary/30">
                    {resolveName(s)}
                    <span className="ml-0.5 text-[8px] opacity-70">{s}</span>
                  </Badge>
                ))}
                {otherSymbols.map((s) => (
                  <Badge key={s} variant="outline" className="text-[10px] px-1 py-0">
                    {resolveName(s)}
                    <span className="ml-0.5 text-[8px] opacity-70">{s}</span>
                  </Badge>
                ))}
              </span>
            )}
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-2 pt-1">
            {item.url && (
              <Button
                variant="outline"
                size="xs"
                className="gap-1"
                onClick={(e) => {
                  e.stopPropagation()
                  window.open(item.url, "_blank", "noopener,noreferrer")
                }}
              >
                <ExternalLink className="h-3 w-3" />
                查看原文
              </Button>
            )}
            <Button
              variant="outline"
              size="xs"
              className="gap-1"
              onClick={(e) => {
                e.stopPropagation()
                onSelect?.(item.item_id)
              }}
            >
              <MessageSquareShare className="h-3 w-3" />
              发送到 Agent
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
