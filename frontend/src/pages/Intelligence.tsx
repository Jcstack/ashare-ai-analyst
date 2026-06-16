/** Intelligence page — 3 tabs: signal radar, sector rotation, notification timeline. */

import { useSearchParams } from "react-router-dom"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { SignalRadarDashboard } from "@/components/intelligence/SignalRadarDashboard"
import { SectorHeatmap } from "@/components/intelligence/SectorHeatmap"
import { NotificationTimeline } from "@/components/intelligence/NotificationTimeline"
import { Radar } from "lucide-react"

const TABS = [
  { value: "signals", label: "信号雷达" },
  { value: "sectors", label: "板块轮动" },
  { value: "timeline", label: "通知时间线" },
]

export default function Intelligence() {
  const [searchParams, setSearchParams] = useSearchParams()
  const currentTab = searchParams.get("tab") || "signals"
  const effectiveTab = TABS.some((t) => t.value === currentTab) ? currentTab : "signals"

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Radar className="h-5 w-5 text-primary" />
        <h1 className="text-headline">市场情报</h1>
      </div>

      <Tabs value={effectiveTab} onValueChange={(tab) => setSearchParams({ tab })}>
        <TabsList variant="line">
          {TABS.map((tab) => (
            <TabsTrigger key={tab.value} value={tab.value}>
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="signals" className="mt-6">
          <SignalRadarDashboard />
        </TabsContent>

        <TabsContent value="sectors" className="mt-6">
          <SectorHeatmap />
        </TabsContent>

        <TabsContent value="timeline" className="mt-6">
          <NotificationTimeline />
        </TabsContent>
      </Tabs>
    </div>
  )
}
