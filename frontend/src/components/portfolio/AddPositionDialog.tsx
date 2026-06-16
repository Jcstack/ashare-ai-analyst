import { useState, useEffect, useRef } from "react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Search, Loader2 } from "lucide-react"
import { useStockSearch } from "@/hooks/useSearch"
import { detectBoard } from "@/hooks/usePortfolio"
import { BOARD_LABELS } from "@/lib/constants"
import type { Position, BoardType } from "@/types/portfolio"
import type { StockSearchItem } from "@/types/search"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (pos: Omit<Position, "id">) => Promise<unknown> | void
  editPosition?: Position | null
  preselectedStock?: { symbol: string; name: string; board: string } | null
}

export function AddPositionDialog({ open, onOpenChange, onSubmit, editPosition, preselectedStock }: Props) {
  const [searchQuery, setSearchQuery] = useState("")
  const [debouncedQuery, setDebouncedQuery] = useState("")
  const [selectedStock, setSelectedStock] = useState<{ symbol: string; name: string; board: BoardType } | null>(null)
  const [shares, setShares] = useState("")
  const [costPrice, setCostPrice] = useState("")
  const [buyDate, setBuyDate] = useState("")
  const [showResults, setShowResults] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const searchRef = useRef<HTMLInputElement>(null)

  const { data: searchResults = [], isLoading: searchLoading } = useStockSearch(debouncedQuery)

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(searchQuery.trim()), 300)
    return () => clearTimeout(timer)
  }, [searchQuery])

  // Reset form when dialog opens/closes or editPosition changes
  useEffect(() => {
    if (open) {
      if (editPosition) {
        setSelectedStock({
          symbol: editPosition.symbol,
          name: editPosition.name,
          board: editPosition.board,
        })
        setShares(String(editPosition.shares))
        setCostPrice(String(editPosition.costPrice))
        setBuyDate(editPosition.buyDate)
        setSearchQuery("")
      } else if (preselectedStock) {
        setSelectedStock({
          symbol: preselectedStock.symbol,
          name: preselectedStock.name,
          board: detectBoard(preselectedStock.symbol),
        })
        setShares("")
        setCostPrice("")
        setBuyDate(new Date().toISOString().slice(0, 10))
        setSearchQuery("")
      } else {
        setSelectedStock(null)
        setShares("")
        setCostPrice("")
        setBuyDate(new Date().toISOString().slice(0, 10))
        setSearchQuery("")
      }
      setShowResults(false)
      setSubmitting(false)
    }
  }, [open, editPosition, preselectedStock])

  const handleSelectStock = (item: StockSearchItem) => {
    setSelectedStock({
      symbol: item.symbol,
      name: item.name,
      board: detectBoard(item.symbol),
    })
    setSearchQuery("")
    setShowResults(false)
  }

  const handleSubmit = async () => {
    if (!selectedStock || submitting) return
    const sharesNum = parseInt(shares, 10)
    const priceNum = parseFloat(costPrice)
    if (isNaN(sharesNum) || sharesNum <= 0 || sharesNum % 100 !== 0) return
    if (isNaN(priceNum) || priceNum <= 0) return

    setSubmitting(true)
    try {
      await onSubmit({
        symbol: selectedStock.symbol,
        name: selectedStock.name,
        board: selectedStock.board,
        shares: sharesNum,
        costPrice: priceNum,
        buyDate: buyDate || new Date().toISOString().slice(0, 10),
      })
      onOpenChange(false)
    } catch {
      // Error toast is handled by the mutation's onError callback
    } finally {
      setSubmitting(false)
    }
  }

  const isValid = selectedStock && shares && costPrice
    && parseInt(shares, 10) > 0
    && parseInt(shares, 10) % 100 === 0
    && parseFloat(costPrice) > 0

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{editPosition ? "编辑持仓" : "添加持仓"}</DialogTitle>
          <DialogDescription>
            {editPosition ? "修改持仓信息" : "搜索股票并输入持仓信息"}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {/* Stock search */}
          <div className="space-y-2">
            <Label>股票</Label>
            {selectedStock ? (
              <div className="flex items-center justify-between rounded-md border px-3 py-2">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm">{selectedStock.symbol}</span>
                  <span className="text-sm">{selectedStock.name}</span>
                  <Badge variant="secondary" className="text-xs">
                    {BOARD_LABELS[selectedStock.board]}
                  </Badge>
                </div>
                {!editPosition && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 text-xs"
                    onClick={() => {
                      setSelectedStock(null)
                      setTimeout(() => searchRef.current?.focus(), 0)
                    }}
                  >
                    更换
                  </Button>
                )}
              </div>
            ) : (
              <div className="relative">
                <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  ref={searchRef}
                  placeholder="输入代码或名称搜索..."
                  value={searchQuery}
                  onChange={(e) => {
                    setSearchQuery(e.target.value)
                    setShowResults(true)
                  }}
                  onFocus={() => setShowResults(true)}
                  className="pl-9"
                />
                {showResults && debouncedQuery.length >= 1 && (
                  <div className="absolute z-10 mt-1 w-full rounded-md border bg-popover shadow-md max-h-48 overflow-y-auto">
                    {searchLoading ? (
                      <div className="flex items-center justify-center py-4">
                        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                      </div>
                    ) : searchResults.length === 0 ? (
                      <div className="py-4 text-center text-sm text-muted-foreground">
                        未找到相关股票
                      </div>
                    ) : (
                      searchResults.map((item) => (
                        <button
                          key={item.symbol}
                          className="flex items-center gap-2 w-full px-3 py-2 text-sm hover:bg-accent transition-colors"
                          onClick={() => handleSelectStock(item)}
                        >
                          <span className="font-mono">{item.symbol}</span>
                          <span>{item.name}</span>
                          <Badge variant="secondary" className="text-xs ml-auto">
                            {BOARD_LABELS[item.board] ?? item.board}
                          </Badge>
                        </button>
                      ))
                    )}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Shares */}
          <div className="space-y-2">
            <Label>持仓数量（股）</Label>
            <Input
              type="number"
              step={100}
              min={100}
              placeholder="100"
              value={shares}
              onChange={(e) => setShares(e.target.value)}
            />
            {shares && parseInt(shares, 10) % 100 !== 0 && (
              <p className="text-xs text-destructive">A股交易以100股（1手）为单位</p>
            )}
          </div>

          {/* Cost price */}
          <div className="space-y-2">
            <Label>成本价（元）</Label>
            <Input
              type="number"
              step={0.01}
              min={0.01}
              placeholder="10.00"
              value={costPrice}
              onChange={(e) => setCostPrice(e.target.value)}
            />
          </div>

          {/* Buy date */}
          <div className="space-y-2">
            <Label>买入日期</Label>
            <Input
              type="date"
              value={buyDate}
              onChange={(e) => setBuyDate(e.target.value)}
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={handleSubmit} disabled={!isValid || submitting}>
            {submitting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                处理中...
              </>
            ) : editPosition ? "保存" : "添加"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
