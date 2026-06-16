import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { AlertTriangle } from "lucide-react"
import { SignalBadge } from "./SignalBadge"
import { ConfidenceMeter } from "./ConfidenceMeter"
import { RiskBadge } from "./RiskBadge"
import { ReasoningPanel } from "./ReasoningPanel"
import { TREND_LABELS } from "@/lib/constants"
import { formatPrice } from "@/lib/utils"
import type { PredictionResult as PredictionResultType } from "@/types/prediction"

interface PredictionResultProps {
  prediction: PredictionResultType
}

export function PredictionResult({ prediction }: PredictionResultProps) {
  if (prediction.status === "error") {
    return (
      <Card className="border-destructive">
        <CardContent className="py-6">
          <p className="text-destructive">{prediction.message ?? "预测失败"}</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-title">预测结果 — {prediction.symbol}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        {/* Hero: signal + confidence side-by-side */}
        <div className="flex flex-wrap items-center gap-4">
          {prediction.signal && <SignalBadge signal={prediction.signal} />}
          {prediction.risk_level && <RiskBadge level={prediction.risk_level} />}
          {prediction.trend && (
            <span className="text-sm text-muted-foreground">
              趋势: {TREND_LABELS[prediction.trend] ?? prediction.trend}
            </span>
          )}
        </div>

        {prediction.confidence != null && (
          <ConfidenceMeter confidence={prediction.confidence} />
        )}

        {/* Target price range */}
        {prediction.target_price_range && prediction.target_price_range.length === 2 && (
          <>
            <div className="border-t border-white/[0.06]" />
            <div className="text-sm">
              <span className="text-muted-foreground">目标价格区间: </span>
              <span className="price-md font-semibold">
                {formatPrice(prediction.target_price_range[0])} — {formatPrice(prediction.target_price_range[1])}
              </span>
            </div>
          </>
        )}

        {/* Key factors as chips */}
        {prediction.key_factors && prediction.key_factors.length > 0 && (
          <>
            <div className="border-t border-white/[0.06]" />
            <div>
              <p className="text-caption font-semibold text-muted-foreground mb-2">关键因素</p>
              <div className="flex flex-wrap gap-1.5">
                {prediction.key_factors.map((f, i) => (
                  <Badge key={i} variant="secondary" className="text-xs">{f}</Badge>
                ))}
              </div>
            </div>
          </>
        )}

        {/* Risk warnings */}
        {prediction.risk_warnings && prediction.risk_warnings.length > 0 && (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 space-y-1.5">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-destructive">
              <AlertTriangle className="h-3.5 w-3.5" />
              风险提示
            </div>
            <ul className="text-xs text-destructive/80 space-y-1 ml-5 list-disc">
              {prediction.risk_warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Reasoning */}
        {prediction.reasoning && (
          <>
            <div className="border-t border-white/[0.06]" />
            <ReasoningPanel reasoning={prediction.reasoning} />
          </>
        )}
      </CardContent>
    </Card>
  )
}
