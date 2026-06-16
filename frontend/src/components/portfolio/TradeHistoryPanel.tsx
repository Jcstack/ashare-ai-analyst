import { useState, useEffect } from "react"
import { Search } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { useTradeHistory, useTradingProfile } from "@/hooks/useTrades"
import { TradingProfileStats } from "./TradingProfileStats"
import { TradeHistoryTable } from "./TradeHistoryTable"

const PAGE_SIZE = 20

export function TradeHistoryPanel() {
  const [filterInput, setFilterInput] = useState("")
  const [debouncedSymbol, setDebouncedSymbol] = useState("")
  const [limit, setLimit] = useState(PAGE_SIZE)

  // 300ms debounce for symbol filter
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSymbol(filterInput.trim())
      setLimit(PAGE_SIZE) // reset pagination on filter change
    }, 300)
    return () => clearTimeout(timer)
  }, [filterInput])

  const profile = useTradingProfile()
  const history = useTradeHistory(debouncedSymbol || undefined, limit)

  const trades = history.data?.trades ?? []
  const total = history.data?.total ?? 0
  const hasMore = trades.length < total

  return (
    <div className="space-y-4">
      {/* Trading Profile Stats */}
      <TradingProfileStats profile={profile.data} isLoading={profile.isLoading} />

      {/* Filter + Table */}
      <Card>
        <CardContent className="p-0">
          {/* Filter input */}
          <div className="px-4 py-3 border-b">
            <div className="relative w-full max-w-xs">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <input
                type="text"
                value={filterInput}
                onChange={(e) => setFilterInput(e.target.value)}
                placeholder="按股票代码筛选..."
                className="h-8 w-full rounded-md border bg-transparent pl-8 pr-3 text-sm focus:outline-none focus:ring-1 focus:ring-accent-primary"
              />
            </div>
          </div>

          {/* Table */}
          <TradeHistoryTable trades={trades} />

          {/* Load more */}
          {hasMore && (
            <div className="flex justify-center py-3 border-t">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setLimit((l) => l + PAGE_SIZE)}
                disabled={history.isFetching}
              >
                {history.isFetching ? "加载中..." : `加载更多（已显示 ${trades.length}/${total}）`}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
