/** CIO Dashboard — unified intelligence command center (v34.0). */

import { Loader2, Shield } from "lucide-react"
import { useIntelligenceDashboard } from "@/hooks/useIntelligence"
import { MacroBarometer } from "@/components/cio/MacroBarometer"
import { PositionRiskTable } from "@/components/cio/PositionRiskTable"
import { RotationCard } from "@/components/cio/RotationCard"
import { DebatePanel } from "@/components/cio/DebatePanel"
import { ImpactChainPanel } from "@/components/cio/ImpactChainPanel"
import { EquityCurve } from "@/components/cio/EquityCurve"
import { RiskMetrics } from "@/components/cio/RiskMetrics"
import { PositionTreemap } from "@/components/cio/PositionTreemap"
import { MacroCalendar } from "@/components/cio/MacroCalendar"
import { FactorRadarPanel } from "@/components/cio/FactorRadarPanel"

export default function CIODashboard() {
  const { data, isLoading, error } = useIntelligenceDashboard()

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Shield className="h-5 w-5 text-primary" />
        <h1 className="text-headline">CIO 驾驶舱</h1>
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground py-8 justify-center">
          <Loader2 className="h-4 w-4 animate-spin" />
          加载情报数据...
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-destructive p-4 text-sm text-destructive">
          加载失败: {error.message}
        </div>
      )}

      {data && (
        <div className="space-y-5">
          {/* Row 1: Macro barometer + Equity curve + Risk metrics */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
            <MacroBarometer data={data} />
            <EquityCurve />
            <RiskMetrics />
          </div>

          {/* Row 2: Position treemap */}
          <PositionTreemap profiles={data.portfolio.profiles} />

          {/* Row 3: Position risk table */}
          <PositionRiskTable
            profiles={data.portfolio.profiles}
            constraintAlerts={data.constraint_alerts}
          />

          {/* Row 4: Rotation + Debate side by side */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <RotationCard />
            <DebatePanel />
          </div>

          {/* Row 5: Macro calendar + Factor radar */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
            <div className="lg:col-span-2">
              <MacroCalendar />
            </div>
            <FactorRadarPanel />
          </div>

          {/* Row 6: Impact chain analysis */}
          <ImpactChainPanel />
        </div>
      )}
    </div>
  )
}
