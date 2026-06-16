/** Popover for attaching Intelligence Hub items to Agent conversation (Pull mode). */

import { useMemo, useState } from "react"
import { Newspaper, Bookmark, Check } from "lucide-react"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useInfoFeed } from "@/hooks/useInfoHub"
import { CATEGORY_LABELS } from "@/types/info-hub"
import type { InfoItem } from "@/types/info-hub"

const MAX_ATTACH = 5

interface IntelAttachPopoverProps {
  symbol: string
  onAttach: (itemIds: string[]) => void
}

export function IntelAttachPopover({ symbol, onAttach }: IntelAttachPopoverProps) {
  const [open, setOpen] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())

  // Fetch bookmarked + symbol-related items
  const { data: bookmarked } = useInfoFeed({ bookmarked: true, limit: 20 })
  const { data: related } = useInfoFeed({ symbol, limit: 20 })

  const bookmarkedItems = bookmarked?.items ?? []
  const relatedItems = related?.items ?? []

  // Deduplicate
  const deduped = useMemo(() => {
    const seen = new Set<string>()
    const result: InfoItem[] = []
    for (const item of [...relatedItems, ...bookmarkedItems]) {
      if (!seen.has(item.item_id)) {
        seen.add(item.item_id)
        result.push(item)
      }
    }
    return result
  }, [bookmarkedItems, relatedItems])

  const toggleItem = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else if (next.size < MAX_ATTACH) {
        next.add(id)
      }
      return next
    })
  }

  const handleConfirm = () => {
    if (selected.size > 0) {
      onAttach(Array.from(selected))
      setSelected(new Set())
      setOpen(false)
    }
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button className="flex items-center gap-1.5 text-xs text-text-tertiary hover:text-text-secondary transition-colors">
          <Newspaper className="h-3.5 w-3.5" />
          关联情报
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-80 p-0" align="start">
        <div className="p-3 pb-2 border-b">
          <p className="text-sm font-medium">附加情报到分析</p>
          <p className="text-xs text-muted-foreground mt-0.5">
            选择情报项注入 Agent 分析上下文 (最多 {MAX_ATTACH} 条)
          </p>
        </div>

        <Tabs defaultValue="related" className="w-full">
          <TabsList variant="line" className="w-full justify-start px-3 pt-1">
            <TabsTrigger value="related" className="text-xs">关联</TabsTrigger>
            <TabsTrigger value="bookmarked" className="text-xs">收藏</TabsTrigger>
          </TabsList>

          <TabsContent value="related" className="mt-0">
            <ItemList
              items={relatedItems}
              selected={selected}
              onToggle={toggleItem}
            />
          </TabsContent>

          <TabsContent value="bookmarked" className="mt-0">
            <ItemList
              items={bookmarkedItems}
              selected={selected}
              onToggle={toggleItem}
            />
          </TabsContent>
        </Tabs>

        {deduped.length === 0 && (
          <div className="p-6 text-center text-xs text-muted-foreground">
            暂无可关联的情报
          </div>
        )}

        <div className="p-2 border-t flex items-center justify-between">
          <span className="text-xs text-muted-foreground">
            已选 {selected.size}/{MAX_ATTACH}
          </span>
          <Button size="sm" disabled={selected.size === 0} onClick={handleConfirm}>
            注入分析
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  )
}

function ItemList({
  items,
  selected,
  onToggle,
}: {
  items: InfoItem[]
  selected: Set<string>
  onToggle: (id: string) => void
}) {
  if (items.length === 0) {
    return (
      <div className="p-4 text-center text-xs text-muted-foreground">
        暂无情报
      </div>
    )
  }

  return (
    <div className="max-h-48 overflow-y-auto">
      {items.map((item) => {
        const isSelected = selected.has(item.item_id)
        return (
          <button
            key={item.item_id}
            className={`flex items-start gap-2 w-full px-3 py-2 text-left transition-colors ${
              isSelected ? "bg-primary/5" : "hover:bg-accent/50"
            }`}
            onClick={() => onToggle(item.item_id)}
          >
            <div
              className={`mt-0.5 h-4 w-4 rounded-sm border flex items-center justify-center shrink-0 ${
                isSelected
                  ? "bg-primary border-primary text-primary-foreground"
                  : "border-input"
              }`}
            >
              {isSelected && <Check className="h-3 w-3" />}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium line-clamp-1">{item.title}</p>
              <div className="flex items-center gap-1.5 mt-0.5">
                <Badge variant="outline" className="text-[10px] px-1 py-0">
                  {CATEGORY_LABELS[item.category] ?? item.category}
                </Badge>
                <span className="text-[10px] text-muted-foreground">{item.source_name}</span>
                {item.is_bookmarked && (
                  <Bookmark className="h-2.5 w-2.5 text-primary fill-primary" />
                )}
              </div>
            </div>
          </button>
        )
      })}
    </div>
  )
}
