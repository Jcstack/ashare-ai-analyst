/** Rotation plan card — shows sell→buy rotation recommendations. */

import { useState } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Loader2, ArrowRight, RefreshCw } from "lucide-react"
import { useRotationScan } from "@/hooks/useIntelligence"
import type { RotationPlan } from "@/types/cio-dashboard"

function PlanItem({ plan }: { plan: RotationPlan }) {
  return (
    <div className="border rounded-lg p-3 space-y-2">
      <div className="flex items-center gap-2">
        <Badge variant="destructive" className="text-[10px]">卖出</Badge>
        <span className="font-medium text-sm">{plan.sell_name}</span>
        <span className="text-xs text-muted-foreground">{plan.sell_symbol}</span>
      </div>
      <p className="text-xs text-muted-foreground">{plan.sell_reason}</p>

      {plan.buy_candidates.length > 0 && (
        <div className="space-y-1 pt-1">
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <ArrowRight className="h-3 w-3" />
            <span>轮入候选</span>
          </div>
          {plan.buy_candidates.map((c) => (
            <div key={c.symbol} className="flex items-center gap-2 text-xs pl-4">
              <Badge variant="default" className="text-[10px]">买入</Badge>
              <span className="font-medium">{c.name}</span>
              <span className="text-muted-foreground">{c.symbol}</span>
              <span className="text-muted-foreground">{c.sector}</span>
              <span className="font-numeric text-market-up ml-auto">
                {c.score.toFixed(2)}
              </span>
            </div>
          ))}
        </div>
      )}

      {plan.blocked_candidates.length > 0 && (
        <div className="text-[10px] text-muted-foreground pt-1">
          受限: {plan.blocked_candidates.map((b) => `${b.name}(${b.reason})`).join(", ")}
        </div>
      )}

      {plan.risk_notes.length > 0 && (
        <div className="text-[10px] text-warning pt-1">
          {plan.risk_notes.join(" | ")}
        </div>
      )}
    </div>
  )
}

export function RotationCard() {
  const [plans, setPlans] = useState<RotationPlan[]>([])
  const [scanned, setScanned] = useState(false)
  const mutation = useRotationScan()

  const handleScan = () => {
    mutation.mutate(undefined, {
      onSuccess: (data) => {
        setPlans(data.rotation_plans ?? [])
        setScanned(true)
      },
    })
  }

  return (
    <Card>
      <CardContent className="py-4 px-5 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-caption font-medium">轮动扫描</span>
          <Button
            size="sm"
            variant="outline"
            onClick={handleScan}
            disabled={mutation.isPending}
            className="h-7 text-xs"
          >
            {mutation.isPending ? (
              <Loader2 className="h-3 w-3 animate-spin mr-1" />
            ) : (
              <RefreshCw className="h-3 w-3 mr-1" />
            )}
            扫描
          </Button>
        </div>

        {!scanned && !mutation.isPending && (
          <p className="text-xs text-muted-foreground">点击扫描按钮分析持仓轮动机会</p>
        )}

        {scanned && plans.length === 0 && (
          <p className="text-xs text-muted-foreground">当前持仓无需轮动调整</p>
        )}

        {plans.length > 0 && (
          <div className="space-y-2">
            {plans.map((plan, i) => (
              <PlanItem key={i} plan={plan} />
            ))}
          </div>
        )}

        {mutation.isError && (
          <p className="text-xs text-destructive">扫描失败: {mutation.error.message}</p>
        )}
      </CardContent>
    </Card>
  )
}
