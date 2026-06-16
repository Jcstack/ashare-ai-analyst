import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { formatTime } from "@/lib/formatters"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useMarketPulse, useSentimentReport } from "@/hooks/useSentiment"
import { MarketPulse } from "@/components/dashboard/MarketPulse"
import {
  RefreshCw, Globe, Shield, Radio, ChevronDown, Activity,
} from "lucide-react"
import { TrendArrow } from "@/components/ui/status-indicators"
import type { ResonanceEvent } from "@/types/sentiment"

const LEVEL_STYLE: Record<string, { bg: string; border: string; text: string; label: string }> = {
  L3: { bg: "bg-market-up/10", border: "border-market-up/30", text: "text-market-up", label: "全网热议" },
  L2: { bg: "bg-warning/10", border: "border-warning/30", text: "text-warning", label: "破圈传播" },
  L1: { bg: "bg-muted/50", border: "border-muted", text: "text-muted-foreground", label: "小众热点" },
}

const SENTIMENT_STYLE: Record<string, { text: string; label: string }> = {
  positive: { text: "text-market-up", label: "利好" },
  negative: { text: "text-market-down", label: "利空" },
  mixed: { text: "text-warning", label: "分歧" },
  neutral: { text: "text-muted-foreground", label: "中性" },
}

function EventCard({ event, onStockClick }: { event: ResonanceEvent; onStockClick: (sym: string) => void }) {
  const level = LEVEL_STYLE[event.resonance_level] ?? LEVEL_STYLE.L1
  const sentiment = SENTIMENT_STYLE[event.sentiment] ?? SENTIMENT_STYLE.neutral

  return (
    <div className={`rounded-lg border ${level.border} ${level.bg} p-3 space-y-2`}>
      {/* Top row: title + badges */}
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-sm font-medium leading-snug flex-1 min-w-0 line-clamp-2">{event.title}</h3>
        <Badge variant="outline" className={`text-[10px] shrink-0 ${level.text} ${level.border}`}>
          {level.label}
        </Badge>
      </div>

      {/* Bottom row: meta */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-3 text-[11px]">
          <span className="text-muted-foreground">{event.platforms.length} 平台</span>
          <span className={sentiment.text}>{sentiment.label}</span>
          {event.heat_score > 0 && (
            <span className="text-muted-foreground flex items-center gap-1">
              热度
              <span className="inline-block h-1 w-8 rounded-full bg-muted overflow-hidden">
                <span
                  className={`block h-full rounded-full ${
                    event.heat_score >= 70 ? "bg-market-up" : event.heat_score >= 40 ? "bg-warning" : "bg-flat"
                  }`}
                  style={{ width: `${Math.min(event.heat_score, 100)}%` }}
                />
              </span>
            </span>
          )}
        </div>
        {event.related_stocks.length > 0 && (
          <div className="flex items-center gap-1 shrink-0">
            {event.related_stocks.slice(0, 3).map((sym) => (
              <button
                key={sym}
                onClick={() => onStockClick(sym)}
                className="text-[10px] font-mono text-primary hover:underline"
              >
                {sym}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export function SentimentTab() {
  const navigate = useNavigate()
  const { data: pulseData, isLoading, refetch: refetchPulse, isFetching: isFetchingPulse } = useMarketPulse()
  const [showReport, setShowReport] = useState(false)
  const { data: reportData, isLoading: reportLoading, refetch: refetchReport, isFetching: isFetchingReport } = useSentimentReport(undefined, showReport)
  const [showAll, setShowAll] = useState(false)

  const isRefreshing = isFetchingPulse || isFetchingReport
  const handleRefresh = () => {
    refetchPulse()
    if (showReport) refetchReport()
  }

  const hotEvents = pulseData?.hot_events ?? []
  const globalSnapshot = pulseData?.global_snapshot
  const visibleEvents = showAll ? hotEvents : hotEvents.slice(0, 6)

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Radio className="h-4 w-4 text-warning" />
          <h2 className="text-title font-medium">舆情雷达</h2>
          {pulseData?.generated_at && (
            <span className="text-[10px] text-muted-foreground ml-2">
              更新于 {formatTime(pulseData.generated_at)}
            </span>
          )}
        </div>
        <Button size="sm" variant="ghost" onClick={handleRefresh} disabled={isRefreshing} className="h-7 gap-1.5 text-xs">
          <RefreshCw className={`h-3 w-3 ${isRefreshing ? "animate-spin" : ""}`} />
          刷新
        </Button>
      </div>

      {/* Hot Events Grid */}
      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full rounded-lg" />
          ))}
        </div>
      ) : hotEvents.length > 0 ? (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {visibleEvents.map((evt) => (
              <EventCard key={evt.event_id} event={evt} onStockClick={(s) => navigate(`/stock/${s}`)} />
            ))}
          </div>
          {hotEvents.length > 6 && (
            <button
              className="flex items-center gap-1 mx-auto text-xs text-muted-foreground hover:text-foreground transition-colors"
              onClick={() => setShowAll(!showAll)}
            >
              <ChevronDown className={`h-3.5 w-3.5 transition-transform ${showAll ? "rotate-180" : ""}`} />
              {showAll ? "收起" : `查看全部 ${hotEvents.length} 条`}
            </button>
          )}
        </>
      ) : (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center py-10 text-muted-foreground">
            <Radio className="h-6 w-6 mb-2 opacity-30" />
            <p className="text-sm">暂无舆情数据</p>
            <p className="text-xs mt-0.5">盘中将自动扫描多平台热点</p>
          </CardContent>
        </Card>
      )}

      {/* Global Markets + AI Report — side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Global Markets */}
        {globalSnapshot && (
          <Card>
            <CardHeader className="py-3 px-4">
              <CardTitle className="text-sm flex items-center gap-1.5">
                <Globe className="h-4 w-4 text-info" />
                全球市场联动
              </CardTitle>
            </CardHeader>
            <CardContent className="px-4 pb-3 space-y-3">
              {/* Indices */}
              {globalSnapshot.indices.length > 0 && (
                <div className="space-y-1.5">
                  <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">主要指数</p>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                    {globalSnapshot.indices.map((idx) => {
                      const pct = idx.pct_change ?? 0
                      const color = pct > 0 ? "text-market-up" : pct < 0 ? "text-market-down" : "text-muted-foreground"
                      return (
                        <div key={idx.name} className="flex items-center justify-between rounded-md bg-muted/50 px-2.5 py-1.5">
                          <span className="text-xs truncate">{idx.name}</span>
                          <span className={`text-xs font-mono font-medium ${color}`}>
                            {pct > 0 ? "+" : ""}{pct.toFixed(2)}%
                          </span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
              {/* Commodities */}
              {globalSnapshot.commodities.length > 0 && (
                <div className="space-y-1.5">
                  <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">商品期货</p>
                  <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
                    {globalSnapshot.commodities.map((c) => {
                      const pct = c.pct_change ?? 0
                      const color = pct > 0 ? "text-market-up" : pct < 0 ? "text-market-down" : "text-muted-foreground"
                      return (
                        <span key={c.name} className="inline-flex items-center gap-1">
                          <span className="text-muted-foreground">{c.name}</span>
                          <span className={`font-mono ${color}`}>{pct > 0 ? "+" : ""}{pct.toFixed(2)}%</span>
                        </span>
                      )
                    })}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* AI Sentiment Report */}
        <Card>
          <CardHeader className="py-3 px-4">
            <CardTitle className="text-sm flex items-center gap-1.5">
              <Shield className="h-4 w-4 text-accent-primary" />
              AI 舆情研判
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            {!showReport ? (
              <div className="flex flex-col items-center py-6">
                <p className="text-xs text-muted-foreground mb-3">AI 将综合分析当前舆情趋势、政策信号和风险预警</p>
                <Button size="sm" variant="outline" onClick={() => setShowReport(true)} className="gap-1.5">
                  <Activity className="h-3.5 w-3.5" />
                  生成 AI 研判
                </Button>
              </div>
            ) : reportLoading ? (
              <div className="space-y-2 py-4">
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-5/6" />
                <Skeleton className="h-16 w-full mt-2" />
              </div>
            ) : reportData?.status === "success" ? (
              <div className="space-y-3">
                {/* Core trends */}
                {reportData.core_trends && reportData.core_trends.length > 0 && (
                  <div className="space-y-1.5">
                    {reportData.core_trends.slice(0, 4).map((trend, i) => {
                      return (
                        <div key={i} className="flex items-start gap-2 text-xs">
                          <span className="mt-0.5 shrink-0">
                            <TrendArrow direction={trend.sentiment === "positive" ? "up" : trend.sentiment === "negative" ? "down" : "neutral"} size={12} />
                          </span>
                          <div>
                            <span className="font-medium">{trend.topic}</span>
                            {trend.summary && <span className="text-muted-foreground ml-1">{trend.summary}</span>}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
                {/* Sector outlook */}
                {reportData.sector_outlook && (
                  <div className="flex flex-wrap gap-1">
                    {(reportData.sector_outlook.bullish ?? []).slice(0, 4).map((s) => (
                      <Badge key={s} variant="outline" className="text-[10px] text-market-up border-market-up/30">↑ {s}</Badge>
                    ))}
                    {(reportData.sector_outlook.bearish ?? []).slice(0, 4).map((s) => (
                      <Badge key={s} variant="outline" className="text-[10px] text-market-down border-market-down/30">↓ {s}</Badge>
                    ))}
                  </div>
                )}
                {/* Risk alerts */}
                {reportData.risk_alerts && reportData.risk_alerts.length > 0 && (
                  <div className="rounded-md bg-warning/5 border border-warning/20 px-3 py-2 text-xs">
                    <span className="text-warning font-medium">风险预警: </span>
                    <span className="text-muted-foreground">{reportData.risk_alerts.map((a) => a.title).join(" · ")}</span>
                  </div>
                )}
                {/* Overall */}
                {reportData.overall_outlook && (
                  <p className="text-xs text-muted-foreground leading-relaxed">{reportData.overall_outlook}</p>
                )}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground text-center py-4">AI 研判暂不可用，请稍后重试</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Market Pulse (notification feed) */}
      <MarketPulse />

      <p className="text-[10px] text-muted-foreground/50 text-center">舆情分析仅供参考，不构成投资建议</p>
    </div>
  )
}
