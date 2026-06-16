/** Intelligence Hub page — unified information center with sub-page navigation.
 *
 * Sub-pages: 全部情报 | 政策法规 | 宏观经济 | 行业动态 | 公司公告 | 市场行情 | 全球市场 | 事件探索 | 源管理
 *
 * The "市场行情" sub-page embeds the existing Intelligence components
 * (SignalRadarDashboard, SectorHeatmap, NotificationTimeline).
 * The "源管理" sub-page shows the Source Library with health status.
 */

import { useSearchParams } from "react-router-dom"
import { Newspaper, Bookmark } from "lucide-react"
import { CategoryNav } from "@/components/info-hub/CategoryNav"
import { InfoFilterBar } from "@/components/info-hub/InfoFilterBar"
import { InfoFeed } from "@/components/info-hub/InfoFeed"
import { SourceHealthTable } from "@/components/info-hub/SourceHealthTable"
import { SourceMonitorPanel } from "@/components/info-hub/SourceMonitorPanel"
import { EventExplorer } from "@/components/info-hub/EventExplorer"
import { useInfoHubStore } from "@/stores/infoHubStore"
import { useSourcesHealth } from "@/hooks/useInfoHub"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { SignalRadarDashboard } from "@/components/intelligence/SignalRadarDashboard"
import { SectorHeatmap } from "@/components/intelligence/SectorHeatmap"
import { NotificationTimeline } from "@/components/intelligence/NotificationTimeline"
import type { InfoCategory } from "@/types/info-hub"
import { useEffect } from "react"

const MARKET_TABS = [
  { value: "signals", label: "信号雷达" },
  { value: "sectors", label: "板块轮动" },
  { value: "timeline", label: "通知时间线" },
]

export default function IntelligenceHub() {
  const [searchParams, setSearchParams] = useSearchParams()
  const subPage = searchParams.get("sub")
  const { setActiveCategory, bookmarkedOnly, setBookmarkedOnly } = useInfoHubStore()

  // Sync URL sub param to store (only for category sub-pages, not special pages)
  useEffect(() => {
    if (subPage && subPage !== "sources" && subPage !== "events") {
      setActiveCategory(subPage as InfoCategory)
    } else if (!subPage) {
      setActiveCategory(undefined)
    }
  }, [subPage, setActiveCategory])

  const handleSubChange = (sub: string | undefined) => {
    if (sub && sub !== "sources" && sub !== "events") {
      setActiveCategory(sub as InfoCategory)
    } else {
      setActiveCategory(undefined)
    }
    if (sub) {
      setSearchParams({ sub })
    } else {
      setSearchParams({})
    }
  }

  const activeSub = subPage ?? undefined
  const isMarketSubPage = activeSub === "market"
  const isSourcesSubPage = activeSub === "sources"
  const isEventsSubPage = activeSub === "events"
  const showBookmarkToggle = !isMarketSubPage && !isSourcesSubPage && !isEventsSubPage

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Newspaper className="h-5 w-5 text-primary" />
        <h1 className="text-headline">情报中心</h1>
        {showBookmarkToggle && (
          <button
            onClick={() => setBookmarkedOnly(!bookmarkedOnly)}
            className="ml-auto p-1.5 rounded-md transition-colors hover:bg-accent"
            title={bookmarkedOnly ? "显示全部" : "仅显示收藏"}
          >
            <Bookmark
              className={`h-4 w-4 ${bookmarkedOnly ? "fill-current text-primary" : "text-muted-foreground"}`}
            />
          </button>
        )}
      </div>

      <CategoryNav activeSub={activeSub} onSubChange={handleSubChange} />

      {isEventsSubPage ? (
        <EventExplorer />
      ) : isSourcesSubPage ? (
        <SourceLibrarySection />
      ) : isMarketSubPage ? (
        <MarketIntelligenceSection />
      ) : (
        <>
          <InfoFilterBar />
          <InfoFeed />
        </>
      )}
    </div>
  )
}

/** Source Library sub-page — displays all intelligence sources with health status. */
function SourceLibrarySection() {
  const { data: sources, isLoading, error } = useSourcesHealth()

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
        加载源数据...
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center py-12 text-sm text-red-400">
        加载失败: {error instanceof Error ? error.message : "未知错误"}
      </div>
    )
  }

  const totalSources = sources?.length ?? 0
  const downCount = sources?.filter((s) => s.status === "DOWN").length ?? 0
  const warnCount = sources?.filter((s) => s.status === "WARN").length ?? 0

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4 text-sm text-muted-foreground">
        <span>共 {totalSources} 个源</span>
        {downCount > 0 && <span className="text-red-400">{downCount} 离线</span>}
        {warnCount > 0 && <span className="text-yellow-400">{warnCount} 告警</span>}
      </div>
      <SourceHealthTable sources={sources ?? []} />
      <SourceMonitorPanel sources={sources ?? []} />
    </div>
  )
}

/** Embeds existing Intelligence page components for the "市场行情" sub-page. */
function MarketIntelligenceSection() {
  return (
    <Tabs defaultValue="signals">
      <TabsList variant="line">
        {MARKET_TABS.map((tab) => (
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
  )
}
