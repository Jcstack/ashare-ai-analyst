/** Individual signal display card. */

import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import type { MarketSignal } from "@/types/intelligence"
import { SIGNAL_TYPE_LABELS, RISK_LEVEL_LABELS } from "@/types/intelligence"

const RISK_COLORS: Record<string, string> = {
  LOW: "text-green-500 border-green-500/30",
  MODERATE: "text-yellow-500 border-yellow-500/30",
  ELEVATED: "text-orange-500 border-orange-500/30",
  EXTREME: "text-red-500 border-red-500/30",
}

export function SignalCard({ signal }: { signal: MarketSignal }) {
  const typeLabel = SIGNAL_TYPE_LABELS[signal.signal_type] ?? signal.signal_type
  const riskLabel = RISK_LEVEL_LABELS[signal.risk_level] ?? signal.risk_level
  const riskColor = RISK_COLORS[signal.risk_level] ?? ""

  return (
    <Card className="hover:bg-muted/30 transition-colors">
      <CardContent className="py-3 px-4 space-y-2">
        {/* Top row: type badge + risk + confidence */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Badge variant="secondary" className="text-xs">
              {typeLabel}
            </Badge>
            <Badge variant="outline" className={`text-xs ${riskColor}`}>
              {riskLabel}
            </Badge>
            {signal.confirmed && (
              <Badge variant="outline" className="text-xs text-green-500 border-green-500/30">
                已确认
              </Badge>
            )}
          </div>
          <span className="text-xs text-muted-foreground font-numeric">
            {new Date(signal.timestamp).toLocaleString("zh-CN", {
              month: "numeric",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
        </div>

        {/* Summary */}
        <p className="text-sm">{signal.summary_short}</p>
        {signal.summary_detailed && (
          <p className="text-xs text-muted-foreground line-clamp-2">
            {signal.summary_detailed}
          </p>
        )}

        {/* Bottom row: assets + confidence bar */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            {signal.assets.slice(0, 3).map((asset) => (
              <Badge key={asset} variant="outline" className="text-[10px] font-numeric">
                {asset}
              </Badge>
            ))}
            {signal.assets.length > 3 && (
              <span className="text-[10px] text-muted-foreground">
                +{signal.assets.length - 3}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <div className="w-16 h-1.5 rounded-full bg-muted overflow-hidden">
              <div
                className="h-full rounded-full bg-primary transition-all"
                style={{ width: `${signal.confidence_score}%` }}
              />
            </div>
            <span className="text-[10px] text-muted-foreground font-numeric">
              {signal.confidence_score.toFixed(0)}%
            </span>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
