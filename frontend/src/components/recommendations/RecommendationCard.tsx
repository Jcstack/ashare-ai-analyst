/** Recommendation card component — displays a single stock recommendation. */

import { Link } from "react-router-dom"
import { formatTimeShort } from "@/lib/formatters"
import { X, Target, ShieldAlert, TrendingUp, DollarSign, ShoppingCart, Activity, AlertTriangle } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import type { Recommendation } from "@/types/recommendation"

function ScoreBadge({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  const color =
    pct >= 80
      ? "bg-market-up/15 text-market-up border-market-up/30"
      : pct >= 65
        ? "bg-yellow-500/15 text-yellow-600 border-yellow-500/30"
        : "bg-muted text-muted-foreground"
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold ${color}`}
    >
      {pct}分
    </span>
  )
}

const CONFIDENCE_STYLES: Record<string, string> = {
  high: "bg-market-up/15 text-market-up border-market-up/30",
  medium: "bg-yellow-500/15 text-yellow-600 border-yellow-500/30",
  low: "bg-muted text-muted-foreground border-muted",
}
const CONFIDENCE_LABELS: Record<string, string> = {
  high: "高置信",
  medium: "中置信",
  low: "低置信",
}

function ConfidenceBadge({ confidence }: { confidence: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${CONFIDENCE_STYLES[confidence] ?? CONFIDENCE_STYLES.medium}`}
    >
      {CONFIDENCE_LABELS[confidence] ?? confidence}
    </span>
  )
}

const SESSION_LABELS: Record<string, string> = {
  pre_market: "盘前",
  early: "早盘",
  mid: "盘中",
  late: "尾盘",
  post_market: "盘后",
}


export function RecommendationCard({
  rec,
  onDismiss,
  onClick,
  onBuy,
}: {
  rec: Recommendation
  onDismiss: (id: string) => void
  onClick?: (rec: Recommendation) => void
  onBuy?: (rec: Recommendation) => void
}) {
  const isCrossSector = rec.factors?.cross_sector_discovery === 1.0

  return (
    <Card
      className="transition-all hover:shadow-md cursor-pointer"
      onClick={() => onClick?.(rec)}
    >
      <CardContent className="p-4 space-y-3">
        {/* Header: stock name + score + dismiss */}
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            <Link
              to={`/stock/${rec.symbol}`}
              className="font-semibold text-sm hover:text-primary transition-colors"
            >
              {rec.name}
            </Link>
            <span className="text-xs text-muted-foreground">{rec.symbol}</span>
            <ScoreBadge score={rec.score} />
            {rec.confidence && <ConfidenceBadge confidence={rec.confidence} />}
            {rec.ai_analyzed === false && (
              <span className="inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium bg-orange-500/15 text-orange-600 border-orange-500/30">
                仅评分
              </span>
            )}
            {isCrossSector && (
              <Badge variant="outline" className="text-[9px] px-1 py-0 border-info/30 text-info">
                跨行业
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-0.5">
            {onBuy && (
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 text-market-up hover:text-market-up"
                title="买入"
                onClick={(e) => { e.stopPropagation(); onBuy(rec) }}
              >
                <ShoppingCart className="h-3.5 w-3.5" />
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6 text-muted-foreground hover:text-foreground"
              onClick={(e) => { e.stopPropagation(); onDismiss(rec.id) }}
            >
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>

        {/* Session + time */}
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Badge variant="outline" className="text-[10px] px-1.5 py-0">
            {SESSION_LABELS[rec.session] || rec.session}
          </Badge>
          <span>{formatTimeShort(rec.created_at)}</span>
        </div>

        {/* Current / closing price (always shown when available) */}
        {rec.current_price != null && (
          <div className="flex items-center gap-3 text-xs flex-wrap">
            <span className="flex items-center gap-1 text-muted-foreground">
              <Activity className="h-3 w-3 text-info" />
              {rec.market_open ? "现价" : "收盘"}:
              <span className="font-numeric font-medium text-foreground">
                {rec.current_price.toFixed(2)}
              </span>
            </span>
            {rec.current_pct_change != null && (
              <span
                className={`font-numeric font-medium ${rec.current_pct_change >= 0 ? "text-market-up" : "text-market-down"}`}
              >
                {rec.current_pct_change >= 0 ? "+" : ""}
                {rec.current_pct_change.toFixed(2)}%
              </span>
            )}
            {rec.price_vs_entry != null && (
              <Badge
                variant="outline"
                className={`text-[10px] px-1.5 py-0 font-numeric ${rec.price_vs_entry >= 0 ? "border-market-up/30 text-market-up" : "border-market-down/30 text-market-down"}`}
              >
                较介入 {rec.price_vs_entry >= 0 ? "+" : ""}
                {rec.price_vs_entry.toFixed(2)}%
              </Badge>
            )}
            {rec.price_vs_entry != null && Math.abs(rec.price_vs_entry) >= 5 && (
              <span className="flex items-center gap-0.5 text-[10px] text-orange-600">
                <AlertTriangle className="h-3 w-3" />
                介入价已失效
              </span>
            )}
          </div>
        )}

        {/* Reason */}
        {rec.reason && (
          <div className="flex gap-2 text-xs">
            <TrendingUp className="h-3.5 w-3.5 mt-0.5 shrink-0 text-market-up" />
            <p className="text-foreground/80 leading-relaxed">{rec.reason}</p>
          </div>
        )}

        {/* Risk notes */}
        {rec.risk_notes && (
          <div className="flex gap-2 text-xs">
            <ShieldAlert className="h-3.5 w-3.5 mt-0.5 shrink-0 text-yellow-500" />
            <p className="text-muted-foreground leading-relaxed">{rec.risk_notes}</p>
          </div>
        )}

        {/* Entry / target / stop-loss */}
        {(rec.entry_price || rec.target_price || rec.stop_loss) && (
          <div className="flex items-center gap-4 text-xs text-muted-foreground flex-wrap">
            {rec.entry_price && (
              <span className="flex items-center gap-1">
                <DollarSign className="h-3 w-3 text-primary" />
                介入: {rec.entry_price.toFixed(2)}
              </span>
            )}
            {rec.target_price && (
              <span className="flex items-center gap-1">
                <Target className="h-3 w-3 text-market-up" />
                目标: {rec.target_price.toFixed(2)}
              </span>
            )}
            {rec.stop_loss && (
              <span className="flex items-center gap-1">
                <ShieldAlert className="h-3 w-3 text-market-down" />
                止损: {rec.stop_loss.toFixed(2)}
              </span>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
