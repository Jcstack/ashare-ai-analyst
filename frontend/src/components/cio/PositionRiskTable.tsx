/** Position risk table — shows macro profiles with rotation signals. */

import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import type { MacroProfile, ConstraintAlert } from "@/types/cio-dashboard"

const SIGNAL_CONFIG: Record<string, { label: string; variant: "default" | "secondary" | "destructive" | "outline" }> = {
  hold: { label: "持有", variant: "outline" },
  add: { label: "加仓", variant: "default" },
  reduce: { label: "减仓", variant: "secondary" },
  exit: { label: "退出", variant: "destructive" },
}

interface Props {
  profiles: MacroProfile[]
  constraintAlerts?: ConstraintAlert[]
}

export function PositionRiskTable({ profiles, constraintAlerts = [] }: Props) {
  const alertMap = new Map(constraintAlerts.map((a) => [a.symbol, a]))

  if (profiles.length === 0) {
    return (
      <Card>
        <CardContent className="py-6 text-center text-xs text-muted-foreground">
          暂无持仓数据
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardContent className="py-4 px-5 space-y-3">
        <span className="text-caption font-medium">持仓风控</span>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-muted-foreground border-b">
                <th className="text-left py-1.5 font-medium">标的</th>
                <th className="text-left py-1.5 font-medium">板块</th>
                <th className="text-center py-1.5 font-medium">宏观评分</th>
                <th className="text-center py-1.5 font-medium">主因</th>
                <th className="text-center py-1.5 font-medium">信号</th>
                <th className="text-left py-1.5 font-medium">备注</th>
              </tr>
            </thead>
            <tbody>
              {profiles.map((p) => {
                const sig = SIGNAL_CONFIG[p.rotation_signal] ?? SIGNAL_CONFIG.hold
                const alert = alertMap.get(p.symbol)
                return (
                  <tr key={p.symbol} className="border-b border-border/50 last:border-0">
                    <td className="py-2">
                      <span className="font-medium">{p.name}</span>
                      <span className="text-muted-foreground ml-1">{p.symbol}</span>
                    </td>
                    <td className="py-2 text-muted-foreground">{p.sector}</td>
                    <td className="py-2 text-center">
                      <span
                        className={`font-numeric ${
                          p.macro_score > 0.2
                            ? "text-market-up"
                            : p.macro_score < -0.2
                              ? "text-market-down"
                              : "text-muted-foreground"
                        }`}
                      >
                        {p.macro_score > 0 ? "+" : ""}
                        {p.macro_score.toFixed(2)}
                      </span>
                    </td>
                    <td className="py-2 text-center text-muted-foreground">{p.top_factor}</td>
                    <td className="py-2 text-center">
                      <Badge variant={sig.variant} className="text-[10px]">
                        {sig.label}
                      </Badge>
                    </td>
                    <td className="py-2">
                      {alert && (
                        <span className="text-warning">{alert.violations.join("; ")}</span>
                      )}
                      {!alert && p.rotation_reason && (
                        <span className="text-muted-foreground">{p.rotation_reason}</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}
