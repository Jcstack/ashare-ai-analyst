/** Dialog for configuring intel analysis before sending to Agent ChatSheet. */

import { useMemo, useState } from "react"
import { Search } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Textarea } from "@/components/ui/textarea"
import { useWatchlist } from "@/hooks/useStocks"
import { usePortfolio } from "@/hooks/usePortfolio"
import type { InfoItem } from "@/types/info-hub"

export interface AnalysisConfig {
  symbol?: string
  /** Resolved display name for the symbol (e.g. "博纳影业"). */
  symbolName?: string
  angle?: string
  /** All portfolio/watchlist symbols that overlap with selected items' related_symbols. */
  matchedPortfolioSymbols?: string[]
  /** Free-form user prompt for custom analysis direction. */
  customPrompt?: string
}

interface IntelAnalysisDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  items: InfoItem[]
  onAnalyze: (config: AnalysisConfig) => void
}

const ANALYSIS_ANGLES = [
  { value: "impact", label: "对持仓影响" },
  { value: "sector", label: "板块机会" },
  { value: "risk", label: "风险预警" },
  { value: "general", label: "综合分析" },
]

export function IntelAnalysisDialog({
  open,
  onOpenChange,
  items,
  onAnalyze,
}: IntelAnalysisDialogProps) {
  const [search, setSearch] = useState("")
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null)
  const [selectedAngle, setSelectedAngle] = useState<string>("general")
  const [customPrompt, setCustomPrompt] = useState("")

  const { data: watchlist } = useWatchlist()
  const { positions } = usePortfolio()

  // Build tracked symbols map (portfolio + watchlist)
  const trackedMap = useMemo(() => {
    const map = new Map<string, { name: string; held: boolean }>()
    for (const w of watchlist ?? []) map.set(w.symbol, { name: w.name, held: false })
    for (const p of positions) map.set(p.symbol, { name: p.name, held: true })
    return map
  }, [watchlist, positions])

  // Auto-extract symbols from selected items with name resolution
  const { matchedSuggestions, otherSuggestions } = useMemo(() => {
    const symbolCounts = new Map<string, number>()
    const nameMap: Record<string, string> = {}
    for (const item of items) {
      const names = item.related_symbol_names ?? {}
      for (const s of item.related_symbols) {
        symbolCounts.set(s, (symbolCounts.get(s) ?? 0) + 1)
        if (names[s]) nameMap[s] = names[s]
      }
    }

    const matched: { symbol: string; name: string; count: number; held: boolean }[] = []
    const other: { symbol: string; name: string; count: number }[] = []

    for (const [symbol, count] of symbolCounts) {
      const tracked = trackedMap.get(symbol)
      const name = tracked?.name ?? nameMap[symbol] ?? symbol
      if (tracked) {
        matched.push({ symbol, name, count, held: tracked.held })
      } else {
        other.push({ symbol, name, count })
      }
    }

    // Sort: held first, then by frequency
    matched.sort((a, b) => (a.held === b.held ? b.count - a.count : a.held ? -1 : 1))
    other.sort((a, b) => b.count - a.count)

    return { matchedSuggestions: matched, otherSuggestions: other }
  }, [items, trackedMap])

  // Merge watchlist into a quick-pick list (excluding already suggested)
  const suggestedSymbolSet = useMemo(() => {
    const s = new Set<string>()
    for (const m of matchedSuggestions) s.add(m.symbol)
    for (const o of otherSuggestions) s.add(o.symbol)
    return s
  }, [matchedSuggestions, otherSuggestions])

  const quickPicks = useMemo(() => {
    if (!watchlist) return []
    const positionSymbols = new Set(positions.map((p) => p.symbol))
    return watchlist
      .filter((w) => !suggestedSymbolSet.has(w.symbol))
      .map((w) => ({
        symbol: w.symbol,
        name: w.name,
        held: positionSymbols.has(w.symbol),
      }))
  }, [watchlist, positions, suggestedSymbolSet])

  // Category tags from selected items
  const categoryTags = useMemo(() => {
    const cats = new Set<string>()
    for (const item of items) {
      if (item.category) cats.add(item.category)
    }
    return Array.from(cats)
  }, [items])

  // Filter quick picks by search
  const filtered = useMemo(() => {
    if (!search) return quickPicks
    const q = search.toLowerCase()
    return quickPicks.filter(
      (s) => s.symbol.toLowerCase().includes(q) || s.name.toLowerCase().includes(q),
    )
  }, [quickPicks, search])

  const handleConfirm = () => {
    const angleLabel = ANALYSIS_ANGLES.find((a) => a.value === selectedAngle)?.label
    const portfolioMatches = matchedSuggestions.map((m) => m.symbol)
    // Resolve display name from suggestions / tracked map
    let symbolName: string | undefined
    if (selectedSymbol) {
      const fromSuggestions =
        matchedSuggestions.find((m) => m.symbol === selectedSymbol)?.name ??
        otherSuggestions.find((o) => o.symbol === selectedSymbol)?.name
      const fromTracked = trackedMap.get(selectedSymbol)?.name
      symbolName = fromSuggestions ?? fromTracked
    }
    onAnalyze({
      symbol: selectedSymbol ?? undefined,
      symbolName,
      angle: angleLabel,
      matchedPortfolioSymbols: portfolioMatches.length > 0 ? portfolioMatches : undefined,
      customPrompt: customPrompt.trim() || undefined,
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="text-title">关联分析</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {/* Selected intel summary */}
          <div className="space-y-1.5">
            <p className="text-xs text-muted-foreground">
              已选择 {items.length} 条情报
            </p>
            {categoryTags.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {categoryTags.map((cat) => (
                  <Badge key={cat} variant="secondary" className="text-[10px]">
                    {cat}
                  </Badge>
                ))}
              </div>
            )}
          </div>

          {/* Analysis angle selector */}
          <div className="space-y-1.5">
            <p className="text-xs text-muted-foreground">分析角度</p>
            <div className="flex flex-wrap gap-1.5">
              {ANALYSIS_ANGLES.map((angle) => (
                <Badge
                  key={angle.value}
                  variant={selectedAngle === angle.value ? "default" : "outline"}
                  className="cursor-pointer text-xs"
                  onClick={() => setSelectedAngle(angle.value)}
                >
                  {angle.label}
                </Badge>
              ))}
            </div>
          </div>

          {/* Custom analysis prompt */}
          <div className="space-y-1.5">
            <p className="text-xs text-muted-foreground">自定义分析要求（可选）</p>
            <Textarea
              value={customPrompt}
              onChange={(e) => setCustomPrompt(e.target.value)}
              placeholder="输入具体分析方向，例如：分析这些消息对半导体板块的短期影响..."
              className="text-sm resize-none"
              rows={2}
              maxLength={500}
            />
          </div>

          {/* Matched portfolio/watchlist symbols — auto-detected from items */}
          {matchedSuggestions.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-xs text-muted-foreground">
                情报关联的持仓/自选股
              </p>
              <div className="flex flex-wrap gap-1.5">
                {matchedSuggestions.map((m) => (
                  <Badge
                    key={m.symbol}
                    variant={selectedSymbol === m.symbol ? "default" : "outline"}
                    className={`cursor-pointer text-xs ${
                      selectedSymbol !== m.symbol
                        ? "bg-primary/10 text-primary border-primary/30"
                        : ""
                    }`}
                    onClick={() =>
                      setSelectedSymbol(selectedSymbol === m.symbol ? null : m.symbol)
                    }
                  >
                    {m.name}
                    <span className="ml-1 opacity-60">{m.symbol}</span>
                    {m.held && <span className="ml-1 text-[10px] opacity-70">持仓</span>}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {/* Other related symbols from items (not in portfolio/watchlist) */}
          {otherSuggestions.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-xs text-muted-foreground">其他关联标的（可选）</p>
              <div className="flex flex-wrap gap-1.5">
                {otherSuggestions.slice(0, 8).map((s) => (
                  <Badge
                    key={s.symbol}
                    variant={selectedSymbol === s.symbol ? "default" : "outline"}
                    className="cursor-pointer text-xs"
                    onClick={() =>
                      setSelectedSymbol(selectedSymbol === s.symbol ? null : s.symbol)
                    }
                  >
                    {s.name}
                    {s.name !== s.symbol && (
                      <span className="ml-1 opacity-60">{s.symbol}</span>
                    )}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {/* Search for a specific stock (optional) */}
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              placeholder="搜索关联股票（可选）..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-8 h-8 text-sm"
            />
          </div>

          {/* Quick picks from watchlist/portfolio */}
          <div className="max-h-36 overflow-y-auto space-y-0.5">
            {search && filtered.length === 0 && (
              <p className="text-xs text-muted-foreground text-center py-4">
                未找到匹配的股票
              </p>
            )}
            {filtered.map((stock) => (
              <button
                key={stock.symbol}
                className={`flex items-center gap-2 w-full rounded-md px-3 py-2 text-left text-sm transition-colors ${
                  selectedSymbol === stock.symbol
                    ? "bg-primary/10 text-primary"
                    : "hover:bg-accent/50"
                }`}
                onClick={() =>
                  setSelectedSymbol(selectedSymbol === stock.symbol ? null : stock.symbol)
                }
              >
                <span className="font-numeric text-xs w-16 shrink-0">{stock.symbol}</span>
                <span className="flex-1 truncate">{stock.name}</span>
                {stock.held && (
                  <Badge variant="secondary" className="text-[10px]">
                    持仓
                  </Badge>
                )}
              </button>
            ))}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button size="sm" onClick={handleConfirm}>
            开始分析
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
