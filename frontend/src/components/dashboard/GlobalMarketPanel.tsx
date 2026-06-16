import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Globe, TrendingUp, TrendingDown } from "lucide-react"
import { useGlobalMarketSnapshot } from "@/hooks/useMarket"
import type { GlobalIndexItem, GlobalCommodityItem, GlobalCurrencyItem } from "@/types/market"

function PriceChange({ change, pct }: { change: number | null; pct: number | null }) {
  if (change == null || pct == null) return <span className="text-muted-foreground">--</span>

  // A-share convention: red for up, green for down
  const color = pct > 0 ? "var(--color-market-up)" : pct < 0 ? "var(--color-market-down)" : "var(--color-market-flat)"
  const sign = pct > 0 ? "+" : ""
  const Icon = pct > 0 ? TrendingUp : pct < 0 ? TrendingDown : null

  return (
    <span className="flex items-center gap-0.5 font-numeric" style={{ color }}>
      {Icon && <Icon className="h-3 w-3" />}
      {sign}{pct.toFixed(2)}%
    </span>
  )
}

function IndexRow({ item }: { item: GlobalIndexItem }) {
  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-xs truncate max-w-[80px]" title={item.symbol}>{item.name}</span>
      <div className="flex items-center gap-2 text-xs">
        <span className="font-numeric text-muted-foreground">
          {item.price != null ? item.price.toLocaleString(undefined, { maximumFractionDigits: 0 }) : "--"}
        </span>
        <PriceChange change={item.change} pct={item.pct_change} />
      </div>
    </div>
  )
}

function CommodityRow({ item }: { item: GlobalCommodityItem }) {
  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-xs">{item.name}</span>
      <div className="flex items-center gap-2 text-xs">
        <span className="font-numeric text-muted-foreground">
          {item.price != null ? item.price.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "--"}
        </span>
        <PriceChange change={item.change} pct={item.pct_change} />
      </div>
    </div>
  )
}

function CurrencyRow({ item }: { item: GlobalCurrencyItem }) {
  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-xs">{item.name}</span>
      <div className="flex items-center gap-2 text-xs">
        <span className="font-numeric text-muted-foreground">
          {item.price != null ? item.price.toFixed(4) : "--"}
        </span>
        <PriceChange change={item.change} pct={item.pct_change} />
      </div>
    </div>
  )
}

export function GlobalMarketPanel() {
  const { data: snapshot, isLoading, error } = useGlobalMarketSnapshot()

  if (error && !snapshot) {
    return null // Silently hide when unavailable
  }

  // Group indices by region
  const indexByRegion = new Map<string, GlobalIndexItem[]>()
  for (const idx of snapshot?.indices ?? []) {
    const region = idx.region || "其他"
    const group = indexByRegion.get(region) ?? []
    group.push(idx)
    indexByRegion.set(region, group)
  }

  return (
    <Card>
      <CardHeader className="py-3 px-4">
        <CardTitle className="text-title flex items-center gap-2">
          <Globe className="h-4 w-4 text-info" />
          外盘行情
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-3">
        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-5 w-full" />
            ))}
          </div>
        ) : (
          <div className="space-y-3">
            {/* Indices by region */}
            {Array.from(indexByRegion.entries()).map(([region, items]) => (
              <div key={region}>
                <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">{region}</div>
                <div className="divide-y divide-border/50">
                  {items.map((item) => (
                    <IndexRow key={item.symbol} item={item} />
                  ))}
                </div>
              </div>
            ))}

            {/* Commodities */}
            {(snapshot?.commodities?.length ?? 0) > 0 && (
              <div>
                <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">大宗商品</div>
                <div className="divide-y divide-border/50">
                  {snapshot!.commodities.map((item) => (
                    <CommodityRow key={item.symbol} item={item} />
                  ))}
                </div>
              </div>
            )}

            {/* Currencies */}
            {(snapshot?.currencies?.length ?? 0) > 0 && (
              <div>
                <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">汇率</div>
                <div className="divide-y divide-border/50">
                  {snapshot!.currencies.map((item) => (
                    <CurrencyRow key={item.symbol} item={item} />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
