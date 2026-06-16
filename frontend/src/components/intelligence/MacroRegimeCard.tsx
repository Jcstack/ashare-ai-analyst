/** Macro regime display card. */

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { useMacroRegime } from "@/hooks/useMarketIntelligence"
import { Globe } from "lucide-react"

const REGIME_STYLES: Record<string, { label: string; color: string }> = {
  risk_on: { label: "风险偏好", color: "text-green-500 border-green-500/30" },
  risk_off: { label: "风险规避", color: "text-red-500 border-red-500/30" },
  transitioning: { label: "转换中", color: "text-yellow-500 border-yellow-500/30" },
  unknown: { label: "未知", color: "text-muted-foreground" },
}

export function MacroRegimeCard() {
  const { data, isLoading } = useMacroRegime()

  if (isLoading) {
    return (
      <Card>
        <CardContent className="py-4 space-y-3">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-12 w-full" />
        </CardContent>
      </Card>
    )
  }

  if (!data || data.error) {
    return (
      <Card>
        <CardContent className="py-6 text-center text-sm text-muted-foreground">
          宏观体制数据暂不可用
        </CardContent>
      </Card>
    )
  }

  const regime = data.regime || "unknown"
  const style = REGIME_STYLES[regime] ?? REGIME_STYLES.unknown

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <Globe className="h-4 w-4" />
          宏观体制
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center gap-3">
          <Badge variant="outline" className={`text-xs ${style.color}`}>
            {style.label}
          </Badge>
          {data.confidence != null && (
            <span className="text-xs text-muted-foreground font-numeric">
              置信度 {(data.confidence * 100).toFixed(0)}%
            </span>
          )}
        </div>

        {data.explanation && (
          <p className="text-xs text-muted-foreground leading-relaxed">
            {data.explanation}
          </p>
        )}

        {data.indicators && Object.keys(data.indicators).length > 0 && (
          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
            {Object.entries(data.indicators).map(([key, val]) => (
              <div key={key} className="flex justify-between">
                <span className="text-muted-foreground">{key}</span>
                <span className="font-numeric font-medium">
                  {typeof val === "number" ? val.toFixed(2) : val}
                </span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
