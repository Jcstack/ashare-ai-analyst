import { useMemo, useState } from "react"
import { Link } from "react-router-dom"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { ExternalLink } from "lucide-react"
import { useConceptConstituents, useConceptHistory } from "@/hooks/useConcept"
import type { StockConceptItem, ConceptConstituentItem, ConceptHistoryRecord } from "@/types/concept"
import { formatAmount } from "@/lib/formatters"

interface ConceptDetailSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  concept: StockConceptItem | null
  currentSymbol?: string
}

function PctText({ value, size = "sm" }: { value: number | null; size?: "sm" | "lg" }) {
  if (value == null) return <span className="text-muted-foreground">-</span>
  const color = value > 0 ? "text-market-up" : value < 0 ? "text-market-down" : "text-muted-foreground"
  const prefix = value > 0 ? "+" : ""
  const sizeClass = size === "lg" ? "text-lg font-bold" : "text-xs"
  return <span className={`font-numeric ${color} ${sizeClass}`}>{prefix}{value.toFixed(2)}%</span>
}

// ---- K-line mini chart (SVG candlestick) ----

const PERIOD_OPTIONS = [
  { label: "30日", days: 30 },
  { label: "60日", days: 60 },
  { label: "120日", days: 120 },
]

function KlineChart({ boardCode }: { boardCode: string }) {
  const [days, setDays] = useState(60)
  const { data, isLoading } = useConceptHistory(boardCode, "daily", days)

  if (isLoading) return <Skeleton className="h-48 w-full" />
  if (!data || data.length === 0) {
    return <div className="h-48 flex items-center justify-center text-xs text-muted-foreground">暂无历史数据</div>
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">板块走势</span>
        <div className="flex items-center gap-1">
          {PERIOD_OPTIONS.map((opt) => (
            <button
              key={opt.days}
              onClick={() => setDays(opt.days)}
              className={`px-2 py-0.5 text-[10px] rounded transition-colors ${
                days === opt.days
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>
      <CandlestickSVG data={data} />
    </div>
  )
}

function CandlestickSVG({ data }: { data: ConceptHistoryRecord[] }) {
  const w = 440
  const h = 180
  const padding = { top: 8, bottom: 20, left: 0, right: 0 }
  const chartW = w - padding.left - padding.right
  const chartH = h - padding.top - padding.bottom

  const allPrices = data.flatMap((d) => [d.high, d.low])
  const minP = Math.min(...allPrices)
  const maxP = Math.max(...allPrices)
  const range = maxP - minP || 1

  const barW = Math.max(1, (chartW / data.length) * 0.7)
  const gap = chartW / data.length

  const yScale = (price: number) => padding.top + chartH - ((price - minP) / range) * chartH

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-48">
      {data.map((d, i) => {
        const x = padding.left + i * gap + gap / 2
        const isUp = d.close >= d.open
        const color = isUp ? "var(--color-market-up)" : "var(--color-market-down)"
        const bodyTop = yScale(Math.max(d.open, d.close))
        const bodyBottom = yScale(Math.min(d.open, d.close))
        const bodyH = Math.max(1, bodyBottom - bodyTop)

        return (
          <g key={i}>
            {/* Wick */}
            <line x1={x} y1={yScale(d.high)} x2={x} y2={yScale(d.low)} stroke={color} strokeWidth="0.8" />
            {/* Body */}
            <rect
              x={x - barW / 2}
              y={bodyTop}
              width={barW}
              height={bodyH}
              fill={isUp ? color : color}
              stroke={color}
              strokeWidth="0.5"
            />
          </g>
        )
      })}
      {/* Price labels */}
      <text x={w - 2} y={padding.top + 10} textAnchor="end" className="fill-muted-foreground" fontSize="9">
        {maxP.toFixed(2)}
      </text>
      <text x={w - 2} y={h - padding.bottom + 12} textAnchor="end" className="fill-muted-foreground" fontSize="9">
        {minP.toFixed(2)}
      </text>
    </svg>
  )
}

// ---- Distribution histogram ----

function DistributionHistogram({
  constituents,
  currentSymbol,
}: {
  constituents: ConceptConstituentItem[]
  currentSymbol?: string
}) {
  const { buckets, currentBucket } = useMemo(() => {
    const pcts = constituents
      .map((s) => s.pct_change)
      .filter((p): p is number => p != null)

    if (pcts.length === 0) return { buckets: [], currentBucket: -1 }

    // Create 7 buckets: <-5%, -5~-3%, -3~-1%, -1~1%, 1~3%, 3~5%, >5%
    const edges = [-Infinity, -5, -3, -1, 1, 3, 5, Infinity]
    const labels = ["<-5%", "-5~-3", "-3~-1", "-1~1", "1~3", "3~5", ">5%"]
    const counts = new Array(7).fill(0)

    for (const p of pcts) {
      for (let i = 0; i < 7; i++) {
        if (p >= edges[i] && p < edges[i + 1]) {
          counts[i]++
          break
        }
      }
    }

    // Find which bucket the current stock falls into
    const currentStock = constituents.find((s) => s.symbol === currentSymbol)
    let curBucket = -1
    if (currentStock?.pct_change != null) {
      const cp = currentStock.pct_change
      for (let i = 0; i < 7; i++) {
        if (cp >= edges[i] && cp < edges[i + 1]) {
          curBucket = i
          break
        }
      }
    }

    return {
      buckets: labels.map((label, i) => ({ label, count: counts[i] })),
      currentBucket: curBucket,
    }
  }, [constituents, currentSymbol])

  if (buckets.length === 0) return null

  const maxCount = Math.max(...buckets.map((b) => b.count), 1)
  const barH = 12
  const barGap = 4
  const svgH = buckets.length * (barH + barGap) + 4
  const labelW = 48
  const chartW = 200

  return (
    <div className="space-y-1">
      <span className="text-xs text-muted-foreground">涨跌分布</span>
      <svg viewBox={`0 0 ${labelW + chartW + 30} ${svgH}`} className="w-full" style={{ height: svgH }}>
        {buckets.map((b, i) => {
          const y = i * (barH + barGap) + 2
          const bw = (b.count / maxCount) * chartW
          const isCurrent = i === currentBucket
          const isGreen = i < 3
          const isRed = i > 3
          const fillColor = isRed ? "var(--color-market-up)" : isGreen ? "var(--color-market-down)" : "#9ca3af"
          const fillOpacity = isCurrent ? 1 : 0.5

          return (
            <g key={i}>
              <text x={labelW - 4} y={y + barH - 2} textAnchor="end" fontSize="9" className="fill-muted-foreground">
                {b.label}
              </text>
              <rect x={labelW} y={y} width={Math.max(bw, 1)} height={barH} rx={2} fill={fillColor} opacity={fillOpacity} />
              {isCurrent && (
                <rect x={labelW} y={y} width={Math.max(bw, 1)} height={barH} rx={2} stroke={fillColor} strokeWidth="1.5" fill="none" />
              )}
              <text x={labelW + bw + 4} y={y + barH - 2} fontSize="9" className="fill-muted-foreground">
                {b.count}
              </text>
            </g>
          )
        })}
      </svg>
      {currentBucket >= 0 && (
        <div className="text-[10px] text-muted-foreground text-center">
          当前个股位于 <span className="font-medium text-foreground">{buckets[currentBucket].label}</span> 区间
        </div>
      )}
    </div>
  )
}

// ---- Constituent list ----

function ConstituentList({
  boardCode,
  currentSymbol,
}: {
  boardCode: string
  currentSymbol?: string
}) {
  const [sortBy, setSortBy] = useState<"pct_change" | "amount">("pct_change")
  const { data, isLoading } = useConceptConstituents(boardCode, sortBy)

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-8 w-full" />
        ))}
      </div>
    )
  }

  if (!data || data.length === 0) {
    return <p className="text-xs text-muted-foreground text-center py-4">暂无成分股数据</p>
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">成分股 ({data.length})</span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setSortBy("pct_change")}
            className={`px-2 py-0.5 text-[10px] rounded ${
              sortBy === "pct_change" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            涨跌幅
          </button>
          <button
            onClick={() => setSortBy("amount")}
            className={`px-2 py-0.5 text-[10px] rounded ${
              sortBy === "amount" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            成交额
          </button>
        </div>
      </div>

      <div className="max-h-[280px] overflow-y-auto space-y-0.5">
        {data.map((stock) => (
          <ConstituentRow key={stock.symbol} stock={stock} isCurrentStock={stock.symbol === currentSymbol} />
        ))}
      </div>
    </div>
  )
}

function ConstituentRow({ stock, isCurrentStock }: { stock: ConceptConstituentItem; isCurrentStock: boolean }) {
  return (
    <Link
      to={`/stock/${stock.symbol}`}
      className={`flex items-center justify-between py-1.5 px-2 rounded transition-colors group ${
        isCurrentStock ? "bg-primary/10 border border-primary/20" : "hover:bg-accent"
      }`}
    >
      <div className="flex items-center gap-2 min-w-0">
        <span className={`text-xs font-medium truncate ${isCurrentStock ? "text-primary" : ""}`}>
          {stock.name}
        </span>
        <span className="text-[10px] text-muted-foreground font-numeric">{stock.symbol}</span>
        {isCurrentStock && (
          <Badge variant="outline" className="text-[9px] px-1 py-0 h-3.5">当前</Badge>
        )}
      </div>
      <div className="flex items-center gap-3 shrink-0">
        {stock.price != null && (
          <span className="text-xs font-numeric">{stock.price.toFixed(2)}</span>
        )}
        <span className="text-xs w-16 text-right">
          <PctText value={stock.pct_change} />
        </span>
        <span className="text-[10px] text-muted-foreground w-14 text-right font-numeric">
          {formatAmount(stock.amount)}
        </span>
        <ExternalLink className="h-3 w-3 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
      </div>
    </Link>
  )
}

// ---- Main Dialog ----

export function ConceptDetailSheet({ open, onOpenChange, concept, currentSymbol }: ConceptDetailSheetProps) {
  if (!concept) return null

  const upDown = concept.up_count + concept.down_count
  const upRatio = upDown > 0 ? ((concept.up_count / upDown) * 100).toFixed(0) : "-"

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {concept.name}
            <Badge variant="outline" className="text-[10px] font-normal">
              {concept.code}
            </Badge>
            <PctText value={concept.pct_change} size="lg" />
          </DialogTitle>
          <DialogDescription className="sr-only">
            概念板块详情: {concept.name}
          </DialogDescription>
        </DialogHeader>

        <div className="grid grid-cols-1 md:grid-cols-5 gap-6">
          {/* Left column: K-line chart (60%) */}
          <div className="md:col-span-3 space-y-4">
            <KlineChart boardCode={concept.code} />

            {/* Stats grid */}
            <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
              <div className="rounded-lg bg-muted/50 p-2 text-center">
                <div className="text-[10px] text-muted-foreground">板块涨跌</div>
                <div className="text-sm font-medium mt-0.5">
                  <PctText value={concept.pct_change} />
                </div>
              </div>
              <div className="rounded-lg bg-muted/50 p-2 text-center">
                <div className="text-[10px] text-muted-foreground">上涨</div>
                <div className="text-sm font-medium mt-0.5 text-market-up">{concept.up_count}</div>
              </div>
              <div className="rounded-lg bg-muted/50 p-2 text-center">
                <div className="text-[10px] text-muted-foreground">下跌</div>
                <div className="text-sm font-medium mt-0.5 text-market-down">{concept.down_count}</div>
              </div>
              <div className="rounded-lg bg-muted/50 p-2 text-center">
                <div className="text-[10px] text-muted-foreground">上涨率</div>
                <div className="text-sm font-medium mt-0.5 font-numeric">{upRatio}%</div>
              </div>
              <div className="rounded-lg bg-muted/50 p-2 text-center">
                <div className="text-[10px] text-muted-foreground">涨停</div>
                <div className="text-sm font-medium mt-0.5 text-market-up font-numeric">{concept.zt_count}</div>
              </div>
              <div className="rounded-lg bg-muted/50 p-2 text-center">
                <div className="text-[10px] text-muted-foreground">跌停</div>
                <div className="text-sm font-medium mt-0.5 text-market-down font-numeric">{concept.dt_count}</div>
              </div>
            </div>

            {/* Amount + rank */}
            <div className="flex items-center justify-between text-xs px-1">
              <span className="text-muted-foreground">成交额: <span className="font-numeric text-foreground">{formatAmount(concept.amount)}</span></span>
              {concept.stock_rank_pct != null && (
                <div className="flex items-center gap-1.5">
                  <span className="text-muted-foreground">个股排名:</span>
                  <div className="h-1.5 w-20 rounded-full bg-muted overflow-hidden">
                    <div
                      className="h-full rounded-full bg-info transition-all"
                      style={{ width: `${(1 - concept.stock_rank_pct) * 100}%` }}
                    />
                  </div>
                  <span className="font-numeric">前{(concept.stock_rank_pct * 100).toFixed(0)}%</span>
                </div>
              )}
            </div>
          </div>

          {/* Right column: Distribution + Constituents (40%) */}
          <div className="md:col-span-2 space-y-4">
            <ConstituentDistribution boardCode={concept.code} currentSymbol={currentSymbol} />
            <div className="border-t" />
            <ConstituentList boardCode={concept.code} currentSymbol={currentSymbol} />
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

/** Wrapper that fetches constituents for distribution chart */
function ConstituentDistribution({ boardCode, currentSymbol }: { boardCode: string; currentSymbol?: string }) {
  const { data } = useConceptConstituents(boardCode, "pct_change")
  if (!data || data.length === 0) return null
  return <DistributionHistogram constituents={data} currentSymbol={currentSymbol} />
}
