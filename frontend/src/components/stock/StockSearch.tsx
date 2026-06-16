import { useState, useEffect, useRef } from "react"
import { Search, Plus, Loader2, Check } from "lucide-react"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useStockSearch } from "@/hooks/useSearch"
import { useAddToWatchlist, useWatchlist } from "@/hooks/useStocks"
import { BOARD_LABELS } from "@/lib/constants"
import { toast } from "sonner"
import type { StockSearchItem } from "@/types/search"

interface StockSearchProps {
  onSelect?: (item: StockSearchItem) => void
  showAddButton?: boolean
  onRequestAddPosition?: (stock: { symbol: string; name: string; board: string }) => void
}

export default function StockSearch({ onSelect, showAddButton = false, onRequestAddPosition }: StockSearchProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const [debouncedQuery, setDebouncedQuery] = useState("")
  const [addedSymbols, setAddedSymbols] = useState<Set<string>>(new Set())
  const inputRef = useRef<HTMLInputElement>(null)

  const { data: results = [], isLoading } = useStockSearch(debouncedQuery)
  const { data: watchlist = [] } = useWatchlist()
  const addMutation = useAddToWatchlist()

  const watchlistSymbols = new Set(watchlist.map((w) => w.symbol))

  // Debounce the query
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(query.trim())
    }, 300)
    return () => clearTimeout(timer)
  }, [query])

  // Focus input when popover opens
  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 0)
      setAddedSymbols(new Set())
    } else {
      setQuery("")
      setDebouncedQuery("")
    }
  }, [open])

  const handleSelect = (item: StockSearchItem) => {
    onSelect?.(item)
    setOpen(false)
  }

  const handleAdd = (e: React.MouseEvent, item: StockSearchItem) => {
    e.stopPropagation()
    addMutation.mutate(
      { symbol: item.symbol, name: item.name, board: item.board },
      {
        onSuccess: () => {
          setAddedSymbols((prev) => new Set(prev).add(item.symbol))
          toast.success(`已添加 ${item.name}(${item.symbol}) 到自选`, {
            action: onRequestAddPosition
              ? {
                  label: "添加持仓",
                  onClick: () =>
                    onRequestAddPosition({
                      symbol: item.symbol,
                      name: item.name,
                      board: item.board,
                    }),
                }
              : undefined,
          })
          setTimeout(() => setOpen(false), 600)
        },
        onError: () => {
          toast.error("添加失败，请重试")
        },
      },
    )
  }

  const isInWatchlist = (symbol: string) => watchlistSymbols.has(symbol) || addedSymbols.has(symbol)

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" className="w-64 justify-start gap-2 text-muted-foreground">
          <Search className="h-4 w-4" />
          <span>搜索股票...</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-96 p-0" align="start">
        <div className="p-2 border-b">
          <Input
            ref={inputRef}
            placeholder="输入代码或名称..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="h-9"
          />
        </div>
        <div className="max-h-64 overflow-y-auto">
          {isLoading && (
            <div className="flex items-center justify-center py-6">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            </div>
          )}
          {!isLoading && debouncedQuery.length >= 1 && results.length === 0 && (
            <div className="py-6 text-center text-sm text-muted-foreground">
              未找到相关股票
            </div>
          )}
          {!isLoading && results.length > 0 && (
            <div className="p-1">
              {results.map((item) => {
                const alreadyAdded = isInWatchlist(item.symbol)
                return (
                  <button
                    key={item.symbol}
                    onClick={() => handleSelect(item)}
                    className="flex items-center justify-between w-full rounded-sm px-2 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground cursor-pointer transition-colors"
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-mono">{item.symbol}</span>
                      <span>{item.name}</span>
                      <Badge variant="secondary" className="text-xs">
                        {BOARD_LABELS[item.board] ?? item.board}
                      </Badge>
                    </div>
                    {showAddButton && (
                      alreadyAdded ? (
                        <span className="inline-flex items-center gap-1 text-xs text-info bg-info/10 rounded-md px-2 py-1">
                          <Check className="h-3 w-3" />
                          已添加
                        </span>
                      ) : (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 px-2 gap-1 text-xs"
                          onClick={(e) => handleAdd(e, item)}
                          disabled={addMutation.isPending}
                        >
                          {addMutation.isPending ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <>
                              <Plus className="h-3 w-3" />
                              添加
                            </>
                          )}
                        </Button>
                      )
                    )}
                  </button>
                )
              })}
            </div>
          )}
          {!isLoading && !debouncedQuery && (
            <div className="py-6 text-center text-sm text-muted-foreground">
              输入股票代码或名称搜索
            </div>
          )}
        </div>
      </PopoverContent>
    </Popover>
  )
}
