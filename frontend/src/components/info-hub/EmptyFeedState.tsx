/** Empty state for the info feed when no items match the current filters. */

import { Inbox } from "lucide-react"

export function EmptyFeedState() {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
      <Inbox className="h-12 w-12 mb-4 opacity-40" />
      <p className="text-sm">暂无情报</p>
      <p className="text-xs mt-1">尝试调整筛选条件或刷新数据源</p>
    </div>
  )
}
