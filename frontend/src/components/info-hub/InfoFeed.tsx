/** Feed container — fetches and renders InfoCard list with accordion expand and multi-select. */

import { useMemo, useState } from "react"
import { useInfoFeed, useToggleBookmark, useMarkRead } from "@/hooks/useInfoHub"
import { useInfoHubStore } from "@/stores/infoHubStore"
import { useWatchlist } from "@/hooks/useStocks"
import { usePortfolio } from "@/hooks/usePortfolio"
import { InfoCard } from "./InfoCard"
import { InfoSelectionBar } from "./InfoSelectionBar"
import { EmptyFeedState } from "./EmptyFeedState"
import { Skeleton } from "@/components/ui/skeleton"
import type { InfoCategory } from "@/types/info-hub"

const MAX_SELECTION = 10

interface InfoFeedProps {
  /** Override category from parent (e.g., sub-page routing). */
  categoryOverride?: InfoCategory
}

export function InfoFeed({ categoryOverride }: InfoFeedProps) {
  const { activeCategory, searchQuery, priorityFilter, bookmarkedOnly, relevanceOnly, sortBy, newItemIds } = useInfoHubStore()
  const category = categoryOverride ?? activeCategory

  // Build a set of tracked symbols (watchlist + portfolio) for relevance matching
  const { data: watchlist } = useWatchlist()
  const { positions } = usePortfolio()
  const trackedSymbols = useMemo(() => {
    const map = new Map<string, string>()
    for (const w of watchlist ?? []) map.set(w.symbol, w.name)
    for (const p of positions) map.set(p.symbol, p.name)
    return map
  }, [watchlist, positions])

  // When "与我相关" is active, pass tracked symbols as comma-separated filter
  const symbolFilter = useMemo(() => {
    if (!relevanceOnly || trackedSymbols.size === 0) return undefined
    return Array.from(trackedSymbols.keys()).join(",")
  }, [relevanceOnly, trackedSymbols])

  const { data, isLoading } = useInfoFeed({
    category,
    priority: priorityFilter,
    search: searchQuery || undefined,
    bookmarked: bookmarkedOnly || undefined,
    symbol: symbolFilter,
    sort_by: sortBy,
    limit: 50,
  })

  const bookmarkMutation = useToggleBookmark()
  const readMutation = useMarkRead()

  // Accordion: only one card expanded at a time
  const [expandedId, setExpandedId] = useState<string | null>(null)

  // Multi-select state
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const selectable = selectedIds.size > 0

  const handleToggleExpand = (itemId: string) => {
    setExpandedId((prev) => (prev === itemId ? null : itemId))
  }

  const handleSelect = (itemId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(itemId)) {
        next.delete(itemId)
      } else if (next.size < MAX_SELECTION) {
        next.add(itemId)
      }
      return next
    })
  }

  const handleClearSelection = () => setSelectedIds(new Set())

  if (isLoading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-24 w-full rounded-lg" />
        ))}
      </div>
    )
  }

  const items = data?.items ?? []

  if (items.length === 0) {
    return <EmptyFeedState />
  }

  const selectedItems = items.filter((item) => selectedIds.has(item.item_id))

  return (
    <>
      <div className="space-y-2">
        {items.map((item) => (
          <InfoCard
            key={item.item_id}
            item={item}
            expanded={expandedId === item.item_id}
            onToggleExpand={handleToggleExpand}
            onBookmark={(id) => bookmarkMutation.mutate(id)}
            onRead={(id) => readMutation.mutate(id)}
            selectable={selectable}
            selected={selectedIds.has(item.item_id)}
            onSelect={handleSelect}
            selectDisabled={selectedIds.size >= MAX_SELECTION}
            trackedSymbols={trackedSymbols}
            isNew={newItemIds.has(item.item_id)}
          />
        ))}
      </div>

      {selectable && (
        <InfoSelectionBar
          count={selectedIds.size}
          max={MAX_SELECTION}
          items={selectedItems}
          onClear={handleClearSelection}
        />
      )}
    </>
  )
}
