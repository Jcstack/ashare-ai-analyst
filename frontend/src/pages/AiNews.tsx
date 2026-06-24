/** Global AI News — aggregated feed from top AI sources. */

import { useState, useCallback } from "react"
import {
  ExternalLink,
  RefreshCw,
  Search,
  Globe,
  BookOpen,
  Users,
  Github,
  ChevronLeft,
  ChevronRight,
} from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { useAiNews, useAiNewsSources, useRefreshAiNews } from "@/hooks/useAiNews"
import type { AiNewsItem } from "@/api/aiNews"

const PAGE_SIZE = 30

const CATEGORIES = [
  { id: "all", label: "全部", icon: Globe },
  { id: "official", label: "官方博客", icon: BookOpen },
  { id: "research", label: "研究论文", icon: BookOpen },
  { id: "community", label: "社区讨论", icon: Users },
  { id: "github", label: "GitHub", icon: Github },
  { id: "search", label: "X/Web搜索", icon: Globe },
] as const

const CATEGORY_COLORS: Record<string, string> = {
  official: "bg-blue-500/10 text-blue-500 border-blue-500/20",
  research: "bg-purple-500/10 text-purple-500 border-purple-500/20",
  community: "bg-amber-500/10 text-amber-500 border-amber-500/20",
  github: "bg-emerald-500/10 text-emerald-500 border-emerald-500/20",
  search: "bg-cyan-500/10 text-cyan-500 border-cyan-500/20",
}

function timeAgo(dateStr: string): string {
  const now = Date.now()
  const date = new Date(dateStr).getTime()
  const diff = now - date
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return "刚刚"
  if (mins < 60) return `${mins}分钟前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}天前`
  return new Date(dateStr).toLocaleDateString("zh-CN")
}

function NewsCard({ item }: { item: AiNewsItem }) {
  return (
    <a
      href={item.url}
      target="_blank"
      rel="noopener noreferrer"
      className="group block rounded-lg border bg-card p-4 transition-all hover:border-primary/30 hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1.5">
            <span className="text-base leading-none">{item.icon}</span>
            <span className="text-xs text-muted-foreground truncate">
              {item.source_name}
            </span>
            <Badge
              variant="outline"
              className={`text-[10px] px-1.5 py-0 ${CATEGORY_COLORS[item.category] || ""}`}
            >
              {item.category}
            </Badge>
            <span className="text-xs text-muted-foreground ml-auto shrink-0">
              {timeAgo(item.published_at)}
            </span>
          </div>
          <h3 className="text-sm font-medium leading-snug line-clamp-2 group-hover:text-primary transition-colors">
            {item.title}
          </h3>
          {item.summary && (
            <p className="mt-1.5 text-xs text-muted-foreground line-clamp-2 leading-relaxed">
              {item.summary}
            </p>
          )}
        </div>
        <ExternalLink className="h-3.5 w-3.5 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0 mt-1" />
      </div>
    </a>
  )
}

function NewsCardSkeleton() {
  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="flex items-center gap-2 mb-2">
        <Skeleton className="h-4 w-4 rounded" />
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-4 w-12 rounded-full" />
      </div>
      <Skeleton className="h-4 w-full mb-2" />
      <Skeleton className="h-3 w-3/4" />
    </div>
  )
}

export default function AiNews() {
  const [category, setCategory] = useState<string>("all")
  const [search, setSearch] = useState("")
  const [searchInput, setSearchInput] = useState("")
  const [sourceFilter, setSourceFilter] = useState<string | undefined>()
  const [page, setPage] = useState(0)

  const { data, isLoading, isFetching } = useAiNews({
    category: category === "all" ? undefined : category,
    source: sourceFilter,
    search: search || undefined,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  })

  const { data: sources } = useAiNewsSources()
  const refreshMutation = useRefreshAiNews()

  const handleRefresh = useCallback(() => {
    refreshMutation.mutate(undefined, {
      onSuccess: (result) => {
        toast.success(`已刷新，获取 ${result.new_items} 条新资讯`)
      },
      onError: () => {
        toast.error("刷新失败，请稍后重试")
      },
    })
  }, [refreshMutation])

  const handleSearch = useCallback(() => {
    setSearch(searchInput)
    setPage(0)
  }, [searchInput])

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="border-b px-6 py-4">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h1 className="text-lg font-bold">AI 全球资讯</h1>
            <p className="text-xs text-muted-foreground mt-0.5">
              汇聚 {sources?.length || 0} 个顶级 AI 信息源 · 实时追踪行业动态
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefresh}
            disabled={refreshMutation.isPending}
          >
            <RefreshCw
              className={`h-3.5 w-3.5 mr-1.5 ${refreshMutation.isPending ? "animate-spin" : ""}`}
            />
            {refreshMutation.isPending ? "刷新中..." : "刷新"}
          </Button>
        </div>

        {/* Category tabs */}
        <div className="flex items-center gap-1.5 mb-3">
          {CATEGORIES.map((cat) => (
            <Button
              key={cat.id}
              variant={category === cat.id ? "default" : "ghost"}
              size="sm"
              className="h-7 text-xs gap-1.5"
              onClick={() => {
                setCategory(cat.id)
                setSourceFilter(undefined)
                setPage(0)
              }}
            >
              <cat.icon className="h-3 w-3" />
              {cat.label}
            </Button>
          ))}
        </div>

        {/* Search */}
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="搜索 AI 资讯..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              className="pl-8 h-8 text-sm"
            />
          </div>
          {search && (
            <Button
              variant="ghost"
              size="sm"
              className="h-8 text-xs"
              onClick={() => {
                setSearch("")
                setSearchInput("")
              }}
            >
              清除
            </Button>
          )}
        </div>
      </div>

      {/* Source summary bar */}
      {sources && sources.length > 0 && (
        <div className="border-b px-6 py-2 flex items-center gap-3 overflow-x-auto text-xs text-muted-foreground">
          {sources.map((s) => (
            <button
              key={s.source_id}
              className={`flex items-center gap-1 shrink-0 transition-colors ${
                sourceFilter === s.source_id
                  ? "text-foreground font-medium"
                  : "hover:text-foreground"
              }`}
              onClick={() => {
                if (sourceFilter === s.source_id) {
                  setSourceFilter(undefined)
                } else {
                  setSourceFilter(s.source_id)
                  setCategory("all")
                }
                setPage(0)
              }}
            >
              <span>{s.icon}</span>
              <span>{s.source_name}</span>
              <span className="text-[10px] text-muted-foreground/60">
                ({s.article_count})
              </span>
              {s.circuit_open && (
                <span className="h-1.5 w-1.5 rounded-full bg-destructive" title="连接异常" />
              )}
            </button>
          ))}
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 8 }).map((_, i) => (
              <NewsCardSkeleton key={i} />
            ))}
          </div>
        ) : data?.items.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
            <Globe className="h-12 w-12 mb-3 opacity-30" />
            <p className="text-sm">
              {search ? "未找到匹配的资讯" : "暂无资讯，点击刷新获取最新内容"}
            </p>
            {!search && (
              <Button
                variant="outline"
                size="sm"
                className="mt-3"
                onClick={handleRefresh}
                disabled={refreshMutation.isPending}
              >
                立即获取
              </Button>
            )}
          </div>
        ) : (
          <>
            <div className="space-y-2">
              {data?.items.map((item) => (
                <NewsCard key={item.id} item={item} />
              ))}
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between mt-4 pt-4 border-t">
                <span className="text-xs text-muted-foreground">
                  共 {data?.total} 条 · 第 {page + 1}/{totalPages} 页
                </span>
                <div className="flex items-center gap-1">
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7"
                    disabled={page === 0}
                    onClick={() => setPage((p) => p - 1)}
                  >
                    <ChevronLeft className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7"
                    disabled={page >= totalPages - 1}
                    onClick={() => setPage((p) => p + 1)}
                  >
                    <ChevronRight className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            )}
          </>
        )}

        {/* Loading overlay for refetching */}
        {isFetching && !isLoading && (
          <div className="fixed bottom-4 right-4 bg-card border rounded-lg px-3 py-1.5 shadow-lg text-xs text-muted-foreground flex items-center gap-2">
            <RefreshCw className="h-3 w-3 animate-spin" />
            更新中...
          </div>
        )}
      </div>
    </div>
  )
}
