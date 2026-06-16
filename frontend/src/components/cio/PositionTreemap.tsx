/** Position treemap — CSS-based position sizing visualization with P&L coloring. */

import { Card, CardContent } from "@/components/ui/card"
import type { MacroProfile } from "@/types/cio-dashboard"

interface Props {
  profiles: MacroProfile[]
}

/**
 * Simple CSS flexbox treemap. Each rectangle is proportional to an equal weight
 * (since we lack actual position value, we size equally and color by macro_score direction).
 * macro_score > 0 = green (favorable), < 0 = red (adverse).
 */
export function PositionTreemap({ profiles }: Props) {
  if (profiles.length === 0) {
    return (
      <Card>
        <CardContent className="py-6 text-center text-xs text-muted-foreground">
          暂无持仓数据
        </CardContent>
      </Card>
    )
  }

  // Use absolute macro_score as a proxy for "weight" — larger scores get more area.
  // Minimum weight so tiny scores still show up.
  const weights = profiles.map((p) => Math.max(Math.abs(p.macro_score), 0.1))
  const totalWeight = weights.reduce((a, b) => a + b, 0)

  return (
    <Card>
      <CardContent className="py-4 px-5 space-y-3">
        <span className="text-caption font-medium">持仓分布</span>
        <div className="flex flex-wrap gap-1 min-h-[120px]">
          {profiles.map((p, i) => {
            const pct = (weights[i] / totalWeight) * 100
            const isPositive = p.macro_score >= 0
            return (
              <div
                key={p.symbol}
                className={`
                  relative rounded-md flex items-center justify-center
                  text-white text-[10px] font-medium overflow-hidden
                  transition-all hover:opacity-90 cursor-default
                  ${isPositive ? "bg-market-up/70" : "bg-market-down/70"}
                `}
                style={{
                  flexBasis: `${Math.max(pct, 8)}%`,
                  flexGrow: pct,
                  minWidth: "60px",
                  minHeight: "48px",
                }}
                title={`${p.name} (${p.symbol}) | 宏观评分: ${p.macro_score > 0 ? "+" : ""}${p.macro_score.toFixed(2)} | 信号: ${p.rotation_signal}`}
              >
                <div className="text-center leading-tight px-1">
                  <div className="truncate">{p.name}</div>
                  <div className="opacity-75 text-[9px]">
                    {p.macro_score > 0 ? "+" : ""}
                    {p.macro_score.toFixed(2)}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
        <div className="flex items-center gap-4 text-[10px] text-muted-foreground">
          <span className="flex items-center gap-1">
            <span className="inline-block w-2 h-2 rounded-sm bg-market-up/70" />
            宏观有利
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-2 h-2 rounded-sm bg-market-down/70" />
            宏观不利
          </span>
          <span>面积 = 评分权重</span>
        </div>
      </CardContent>
    </Card>
  )
}
