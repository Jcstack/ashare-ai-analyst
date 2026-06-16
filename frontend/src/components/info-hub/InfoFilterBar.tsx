/** Search + priority filter bar for the info feed. */

import { useState } from "react"
import { Search, RefreshCw } from "lucide-react"
import { cn } from "@/lib/utils"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useInfoHubStore } from "@/stores/infoHubStore"
import { useRefreshFeed } from "@/hooks/useInfoHub"

export function InfoFilterBar() {
  const { searchQuery, priorityFilter, sortBy, setSearchQuery, setPriorityFilter, setSortBy } = useInfoHubStore()
  const refreshMutation = useRefreshFeed()
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null)

  const handleRefresh = () => {
    setRefreshMsg(null)
    refreshMutation.mutate(undefined, {
      onSuccess: (data) => {
        const msg = data.new_items > 0
          ? `获取到 ${data.new_items} 条新情报`
          : "暂无新情报"
        setRefreshMsg(msg)
        setTimeout(() => setRefreshMsg(null), 4000)
      },
    })
  }

  return (
    <div className="flex items-center gap-3">
      <div className="relative flex-1 max-w-xs">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
        <Input
          placeholder="搜索情报..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="pl-8 h-8 text-sm"
        />
      </div>

      <Select
        value={priorityFilter ?? "all"}
        onValueChange={(v) => setPriorityFilter(v === "all" ? undefined : (v as "breaking" | "high" | "normal" | "low"))}
      >
        <SelectTrigger size="sm" className="w-28 text-sm">
          <SelectValue placeholder="优先级" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">全部</SelectItem>
          <SelectItem value="breaking">突发</SelectItem>
          <SelectItem value="high">重要</SelectItem>
          <SelectItem value="normal">一般</SelectItem>
        </SelectContent>
      </Select>

      <Select
        value={sortBy}
        onValueChange={(v) => setSortBy(v as "time" | "score")}
      >
        <SelectTrigger size="sm" className="w-24 text-sm">
          <SelectValue placeholder="排序" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="time">时间</SelectItem>
          <SelectItem value="score">评分</SelectItem>
        </SelectContent>
      </Select>

      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          className="h-8 gap-1.5"
          onClick={handleRefresh}
          disabled={refreshMutation.isPending}
        >
          <RefreshCw className={cn("h-3.5 w-3.5", refreshMutation.isPending && "animate-spin")} />
          刷新
        </Button>
        {refreshMsg && (
          <span className="text-xs text-muted-foreground animate-in fade-in">{refreshMsg}</span>
        )}
      </div>
    </div>
  )
}
