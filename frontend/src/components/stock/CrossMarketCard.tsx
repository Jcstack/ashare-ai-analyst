import { useState } from "react"
import { formatTime } from "@/lib/formatters"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Globe, TrendingUp, TrendingDown, Minus, Loader2 } from "lucide-react"
import { useCrossMarket } from "@/hooks/useSentiment"
import type { CrossMarketGroup, CrossMarketPeer } from "@/types/sentiment"

interface CrossMarketCardProps {
  symbol: string
}

const TREND_ICON = {
  positive: TrendingUp,
  negative: TrendingDown,
  neutral: Minus,
}

const TREND_COLOR = {
  positive: "text-market-up",
  negative: "text-market-down",
  neutral: "text-market-flat",
}

export function CrossMarketCard({ symbol }: CrossMarketCardProps) {
  const [enabled, setEnabled] = useState(false)
  const { data, isLoading, error } = useCrossMarket(symbol, enabled)

  if (!enabled) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-1.5">
            <Globe className="h-4 w-4 text-info" />
            跨市场关联
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-center py-3 space-y-2">
            <p className="text-xs text-muted-foreground">
              查看海外同行、商品关联和全球市场对该股的影响
            </p>
            <Button size="sm" variant="outline" onClick={() => setEnabled(true)}>
              <Globe className="h-3.5 w-3.5 mr-1.5" />
              查看关联
            </Button>
          </div>
        </CardContent>
      </Card>
    )
  }

  if (isLoading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-1.5">
            <Globe className="h-4 w-4 text-info" />
            跨市场关联
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            正在获取跨市场数据...
          </div>
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-16 w-full" />
        </CardContent>
      </Card>
    )
  }

  if (error || !data) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-1.5">
            <Globe className="h-4 w-4 text-info" />
            跨市场关联
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground text-center py-3">
            跨市场数据暂时不可用
          </p>
        </CardContent>
      </Card>
    )
  }

  const dirColor = data.impact_direction === "positive" ? "text-market-up"
    : data.impact_direction === "negative" ? "text-market-down"
    : "text-market-flat"

  const dirLabel = data.impact_direction === "positive" ? "正面影响"
    : data.impact_direction === "negative" ? "负面影响"
    : "影响中性"

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-1.5">
            <Globe className="h-4 w-4 text-info" />
            跨市场关联
          </CardTitle>
          <div className="flex items-center gap-1.5">
            {data.tags.map((tag) => (
              <Badge key={tag} variant="secondary" className="text-[9px]">{tag}</Badge>
            ))}
            <span className={`text-xs font-medium ${dirColor}`}>{dirLabel}</span>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Impact score bar */}
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-muted-foreground w-16 shrink-0">综合影响</span>
          <div className="h-2 flex-1 bg-muted rounded-full overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: `${Math.min(100, Math.abs(data.combined_impact_score) * 100)}%`,
                backgroundColor: data.impact_direction === "positive" ? "var(--color-market-up)"
                  : data.impact_direction === "negative" ? "var(--color-market-down)"
                  : "var(--color-market-flat)",
              }}
            />
          </div>
          <span className="text-[10px] font-mono text-muted-foreground w-10 text-right">
            {(data.combined_impact_score * 100).toFixed(0)}%
          </span>
        </div>

        {/* Peer groups */}
        <PeerGroupRow label="美股同行" group={data.us_market} />
        <PeerGroupRow label="港股关联" group={data.hk_market} />
        <PeerGroupRow label="商品敞口" group={data.commodity_exposure} />

        {/* Global indices summary */}
        {data.global_indices.summary && (
          <div className="text-[10px] text-muted-foreground border-t pt-2">
            <span className="font-medium">全球指数: </span>
            {data.global_indices.summary}
          </div>
        )}

        <p className="text-[9px] text-muted-foreground/50">{formatTime(data.generated_at)}</p>
      </CardContent>
    </Card>
  )
}

function PeerGroupRow({ label, group }: { label: string; group: CrossMarketGroup }) {
  if (!group.peers || group.peers.length === 0) return null

  const TrendIcon = TREND_ICON[group.trend as keyof typeof TREND_ICON] ?? Minus
  const trendColor = TREND_COLOR[group.trend as keyof typeof TREND_COLOR] ?? "text-market-flat"

  return (
    <div className="flex items-start gap-2 text-xs">
      <div className="flex items-center gap-1 w-16 shrink-0">
        <TrendIcon className={`h-3 w-3 ${trendColor}`} />
        <span className="text-[10px] text-muted-foreground">{label}</span>
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 flex-1">
        {group.peers.map((peer) => (
          <PeerItem key={peer.symbol} peer={peer} />
        ))}
      </div>
      {group.avg_pct_change != null && (
        <span className={`text-[10px] font-mono shrink-0 ${
          group.avg_pct_change > 0 ? "text-market-up" : group.avg_pct_change < 0 ? "text-market-down" : "text-market-flat"
        }`}>
          {group.avg_pct_change > 0 ? "+" : ""}{group.avg_pct_change.toFixed(2)}%
        </span>
      )}
    </div>
  )
}

function PeerItem({ peer }: { peer: CrossMarketPeer }) {
  const pct = peer.pct_change ?? 0
  const color = pct > 0 ? "text-market-up" : pct < 0 ? "text-market-down" : "text-market-flat"

  return (
    <span className="font-mono text-[10px]">
      {peer.symbol}{" "}
      <span className={color}>
        {pct > 0 ? "+" : ""}{pct.toFixed(2)}%
      </span>
    </span>
  )
}
