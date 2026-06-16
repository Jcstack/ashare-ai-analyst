/** Signal radar dashboard — 3 sub-tabs: trends, anomalies, macro. */

import { useState } from "react"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Skeleton } from "@/components/ui/skeleton"
import { SignalCard } from "./SignalCard"
import { MacroRegimeCard } from "./MacroRegimeCard"
import { useTrendRadar, useAnomalyRadar, useSignals } from "@/hooks/useMarketIntelligence"

export function SignalRadarDashboard() {
  const [subTab, setSubTab] = useState("trend")

  return (
    <Tabs value={subTab} onValueChange={setSubTab}>
      <TabsList variant="line" className="mb-4">
        <TabsTrigger value="trend">趋势</TabsTrigger>
        <TabsTrigger value="anomaly">异动</TabsTrigger>
        <TabsTrigger value="macro">宏观</TabsTrigger>
      </TabsList>

      <TabsContent value="trend">
        <TrendPanel />
      </TabsContent>
      <TabsContent value="anomaly">
        <AnomalyPanel />
      </TabsContent>
      <TabsContent value="macro">
        <MacroPanel />
      </TabsContent>
    </Tabs>
  )
}

function TrendPanel() {
  const { data, isLoading } = useTrendRadar()

  if (isLoading) return <LoadingSkeleton />
  if (!data || data.trends.length === 0) {
    return <EmptyState text="暂无趋势信号" />
  }

  return (
    <div className="space-y-3">
      {data.trends.map((trend) => (
        <SignalCard key={trend.asset} signal={trend.latest_signal} />
      ))}
    </div>
  )
}

function AnomalyPanel() {
  const { data, isLoading } = useAnomalyRadar()

  if (isLoading) return <LoadingSkeleton />
  if (!data || data.anomalies.length === 0) {
    return <EmptyState text="暂无异动信号" />
  }

  return (
    <div className="space-y-3">
      {data.anomalies.slice(0, 20).map((sig) => (
        <SignalCard key={sig.signal_id} signal={sig} />
      ))}
    </div>
  )
}

function MacroPanel() {
  const { data: signals, isLoading } = useSignals({
    signal_type: "S8_MACRO_DRIVEN",
    limit: 10,
  })

  return (
    <div className="space-y-4">
      <MacroRegimeCard />
      {isLoading ? (
        <LoadingSkeleton />
      ) : signals && signals.length > 0 ? (
        <div className="space-y-3">
          {signals.map((sig) => (
            <SignalCard key={sig.signal_id} signal={sig} />
          ))}
        </div>
      ) : (
        <EmptyState text="暂无宏观驱动信号" />
      )}
    </div>
  )
}

function LoadingSkeleton() {
  return (
    <div className="space-y-3">
      {[1, 2, 3].map((i) => (
        <Skeleton key={i} className="h-24 w-full rounded-lg" />
      ))}
    </div>
  )
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="py-12 text-center text-sm text-muted-foreground">
      {text}
    </div>
  )
}
