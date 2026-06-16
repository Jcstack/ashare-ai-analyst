import { useState, useEffect, useCallback } from "react"
import { useNavigate } from "react-router-dom"
import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command"
import { Badge } from "@/components/ui/badge"
import { useStockSearch } from "@/hooks/useSearch"
import { BOARD_LABELS } from "@/lib/constants"
import { Clock, Search, TrendingUp } from "lucide-react"

const RECENT_KEY = "cmd-palette-recent"
const MAX_RECENT = 5

function getRecentViewed(): Array<{ symbol: string; name: string; board: string }> {
  try {
    return JSON.parse(localStorage.getItem(RECENT_KEY) || "[]")
  } catch {
    return []
  }
}

function addRecentViewed(item: { symbol: string; name: string; board: string }) {
  const recent = getRecentViewed().filter((r) => r.symbol !== item.symbol)
  recent.unshift(item)
  localStorage.setItem(RECENT_KEY, JSON.stringify(recent.slice(0, MAX_RECENT)))
}

export default function CommandPalette() {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const [debouncedQuery, setDebouncedQuery] = useState("")
  const navigate = useNavigate()

  const { data: results = [], isLoading } = useStockSearch(debouncedQuery)

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault()
        setOpen((prev) => !prev)
      }
    }
    document.addEventListener("keydown", handleKeyDown)
    return () => document.removeEventListener("keydown", handleKeyDown)
  }, [])

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(query.trim())
    }, 300)
    return () => clearTimeout(timer)
  }, [query])

  const handleSelect = useCallback(
    (symbol: string, name: string, board: string) => {
      addRecentViewed({ symbol, name, board })
      setOpen(false)
      setQuery("")
      setDebouncedQuery("")
      navigate(`/stock/${symbol}`)
    },
    [navigate]
  )

  const recentViewed = getRecentViewed()

  return (
    <CommandDialog
      open={open}
      onOpenChange={setOpen}
      shouldFilter={false}
      title="搜索股票"
      description="输入股票代码或名称快速跳转"
    >
      <CommandInput placeholder="搜索股票代码或名称..." value={query} onValueChange={setQuery} />
      <CommandList className="max-h-[400px] overflow-y-auto">
        {isLoading && debouncedQuery.length >= 1 && (
          <div className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
            <div className="flex gap-1">
              <span className="ai-dot" />
              <span className="ai-dot" />
              <span className="ai-dot" />
            </div>
            <span>搜索中...</span>
          </div>
        )}

        {!isLoading && debouncedQuery.length >= 1 && results.length === 0 && (
          <CommandEmpty>
            <div className="flex flex-col items-center gap-1">
              <Search className="h-5 w-5 text-muted-foreground/50" />
              <span>未找到 "{debouncedQuery}" 相关股票</span>
            </div>
          </CommandEmpty>
        )}

        {results.length > 0 && (
          <CommandGroup heading="搜索结果">
            {results.map((item) => (
              <CommandItem
                key={item.symbol}
                value={item.symbol}
                onSelect={() => handleSelect(item.symbol, item.name, item.board)}
                className="flex items-center gap-3 px-3 py-2.5 cursor-pointer"
              >
                <TrendingUp className="h-4 w-4 text-muted-foreground shrink-0" />
                <span className="font-mono text-sm font-medium">{item.symbol}</span>
                <span className="text-sm flex-1">{item.name}</span>
                <Badge variant="secondary" className="text-caption shrink-0">
                  {BOARD_LABELS[item.board] ?? item.board}
                </Badge>
              </CommandItem>
            ))}
          </CommandGroup>
        )}

        {!debouncedQuery && recentViewed.length > 0 && (
          <CommandGroup heading="最近查看">
            {recentViewed.map((item) => (
              <CommandItem
                key={item.symbol}
                value={item.symbol}
                onSelect={() => handleSelect(item.symbol, item.name, item.board)}
                className="flex items-center gap-3 px-3 py-2.5 cursor-pointer"
              >
                <Clock className="h-4 w-4 text-muted-foreground shrink-0" />
                <span className="font-mono text-sm font-medium">{item.symbol}</span>
                <span className="text-sm flex-1">{item.name}</span>
                <Badge variant="secondary" className="text-caption shrink-0">
                  {BOARD_LABELS[item.board] ?? item.board}
                </Badge>
              </CommandItem>
            ))}
          </CommandGroup>
        )}

        {!debouncedQuery && recentViewed.length === 0 && (
          <div className="py-8 text-center text-sm text-muted-foreground">
            输入股票代码或名称开始搜索
          </div>
        )}
      </CommandList>
    </CommandDialog>
  )
}
