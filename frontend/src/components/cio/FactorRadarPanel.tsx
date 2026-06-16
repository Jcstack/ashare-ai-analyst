/** Factor Radar Panel — fetches factor exposure data and renders radar chart. */

import { Loader2, AlertCircle } from "lucide-react"
import { useFactorExposure } from "@/hooks/useIntelligence"
import { FactorRadar } from "./FactorRadar"

export function FactorRadarPanel() {
  const { data, isLoading, error } = useFactorExposure()

  if (isLoading) {
    return (
      <div className="rounded-lg border bg-card p-4 flex items-center justify-center min-h-[260px]">
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-lg border bg-card p-4 flex items-center gap-2 text-sm text-destructive min-h-[260px]">
        <AlertCircle className="h-4 w-4" />
        因子数据加载失败
      </div>
    )
  }

  const factors = data?.factors ?? [
    { label: "动量", value: 0.5, benchmark: 0.5 },
    { label: "价值", value: 0.5, benchmark: 0.5 },
    { label: "波动", value: 0.5, benchmark: 0.5 },
    { label: "流动性", value: 0.5, benchmark: 0.5 },
    { label: "质量", value: 0.5, benchmark: 0.5 },
    { label: "规模", value: 0.5, benchmark: 0.5 },
  ]

  return <FactorRadar factors={factors} />
}
