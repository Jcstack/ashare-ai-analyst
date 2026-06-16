import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Activity,
  Radio,
  Globe,
  Shield,
  TrendingUp,
  TrendingDown,
  Minus,
  RefreshCw,
  ChevronDown,
  ChevronUp,
} from "lucide-react"
import { StatusDot, TrendArrow } from "@/components/ui/status-indicators"
import { useMarketPulse, useSentimentReport } from "@/hooks/useSentiment"
import type { ResonanceEvent, HoldingsNewsItem } from "@/types/sentiment"

const LEVEL_CONFIG: Record<string, { color: string; label: string; level: "high" | "medium" | "low" }> = {
  L3: { color: "var(--color-market-up)", label: "全网热议", level: "high" },
  L2: { color: "var(--semantic-warning)", label: "破圈传播", level: "medium" },
  L1: { color: "var(--color-market-flat)", label: "小众热点", level: "low" },
}

const SENTIMENT_COLOR: Record<string, string> = {
  positive: "var(--color-market-up)",
  negative: "var(--color-market-down)",
  mixed: "var(--semantic-warning)",
  neutral: "var(--color-market-flat)",
}

interface SentimentRadarProps {
  symbols?: string[]
}

export function SentimentRadar({ symbols }: SentimentRadarProps) {
  const { data: pulseData, isLoading: pulseLoading, refetch: refetchPulse, isFetching: isFetchingPulse } = useMarketPulse(symbols)
  const [showReport, setShowReport] = useState(false)
  const { data: reportData, isLoading: reportLoading, refetch: refetchReport, isFetching: isFetchingReport } = useSentimentReport(symbols, showReport)
  const [expanded, setExpanded] = useState(false)

  const isRefreshing = isFetchingPulse || isFetchingReport
  const handleRefresh = () => {
    refetchPulse()
    if (showReport) refetchReport()
  }

  const navigate = useNavigate()

  const hotEvents = pulseData?.hot_events ?? []
  const holdingsNews = pulseData?.holdings_news ?? {}
  const globalSnapshot = pulseData?.global_snapshot
  const hasHoldingsNews = Object.values(holdingsNews).some((items) => items.length > 0)

  return (
    <Card>
      <CardHeader className="py-3 px-4 flex-row items-center justify-between space-y-0">
        <CardTitle className="text-title flex items-center gap-2">
          <Radio className="h-4 w-4 text-warning" />
          舆情雷达
        </CardTitle>
        <Button
          size="icon"
          variant="ghost"
          className="h-6 w-6"
          onClick={handleRefresh}
          disabled={isRefreshing}
        >
          <RefreshCw className={`h-3 w-3 ${isRefreshing ? "animate-spin" : ""}`} />
        </Button>
      </CardHeader>
      <CardContent className="px-4 pb-3 space-y-3">
        {pulseLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
          </div>
        ) : (
          <>
            {/* Hot Events Section */}
            {hotEvents.length > 0 && (
              <HotEventsSection
                events={expanded ? hotEvents : hotEvents.slice(0, 4)}
                onStockClick={(sym) => navigate(`/stock/${sym}`)}
              />
            )}

            {hotEvents.length > 4 && (
              <button
                className="text-[10px] text-muted-foreground hover:text-foreground transition-colors flex items-center gap-0.5 mx-auto"
                onClick={() => setExpanded(!expanded)}
              >
                {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                {expanded ? "收起" : `查看全部 ${hotEvents.length} 条`}
              </button>
            )}

            {/* Holdings-Related News */}
            {hasHoldingsNews && (
              <HoldingsNewsSection
                holdingsNews={holdingsNews}
                onStockClick={(sym) => navigate(`/stock/${sym}`)}
              />
            )}

            {/* Global Market Summary */}
            {globalSnapshot && (
              <GlobalSummarySection snapshot={globalSnapshot} />
            )}

            {/* AI Sentiment Report (on-demand) */}
            {!showReport ? (
              <button
                className="w-full text-[11px] text-primary hover:text-primary/80 border border-dashed border-primary/20 rounded-md py-1.5 transition-colors"
                onClick={() => setShowReport(true)}
              >
                <Activity className="h-3 w-3 inline mr-1" />
                AI 舆情研判
              </button>
            ) : reportLoading ? (
              <div className="space-y-2">
                <Skeleton className="h-6 w-full" />
                <Skeleton className="h-20 w-full" />
              </div>
            ) : reportData?.status === "success" ? (
              <AISentimentSection report={reportData} />
            ) : (
              <p className="text-[10px] text-muted-foreground text-center py-2">
                AI 研判暂不可用
              </p>
            )}

            {/* Empty state */}
            {hotEvents.length === 0 && !hasHoldingsNews && !globalSnapshot && (
              <div className="text-center py-4 text-muted-foreground">
                <Radio className="h-5 w-5 mx-auto mb-1.5 opacity-40" />
                <p className="text-xs">暂无舆情数据，稍后自动刷新</p>
              </div>
            )}
          </>
        )}

        <p className="text-[9px] text-muted-foreground/50 text-center">
          舆情分析仅供参考
        </p>
      </CardContent>
    </Card>
  )
}

function HotEventsSection({
  events,
  onStockClick,
}: {
  events: ResonanceEvent[]
  onStockClick: (sym: string) => void
}) {
  return (
    <div className="space-y-1.5">
      <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
        热点事件
      </p>
      {events.map((evt) => {
        const cfg = LEVEL_CONFIG[evt.resonance_level] ?? LEVEL_CONFIG.L1
        const sentColor = SENTIMENT_COLOR[evt.sentiment] ?? SENTIMENT_COLOR.neutral

        return (
          <div key={evt.event_id} className="flex items-start gap-2 text-xs">
            <StatusDot level={cfg.level} size="sm" className="mt-1" />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5">
                <span className="font-medium truncate">{evt.title}</span>
                <Badge
                  variant="outline"
                  className="text-[8px] px-1 py-0 shrink-0"
                  style={{ borderColor: cfg.color, color: cfg.color }}
                >
                  {cfg.label}
                </Badge>
              </div>
              <div className="flex items-center gap-1.5 mt-0.5">
                <span className="text-[10px] text-muted-foreground">
                  {evt.platforms.length} 平台
                </span>
                <span
                  className="text-[10px]"
                  style={{ color: sentColor }}
                >
                  {evt.sentiment === "positive" ? "利好" :
                   evt.sentiment === "negative" ? "利空" :
                   evt.sentiment === "mixed" ? "分歧" : "中性"}
                </span>
                {evt.related_stocks.length > 0 && (
                  <span className="text-[10px] text-muted-foreground">
                    {evt.related_stocks.map((sym) => (
                      <button
                        key={sym}
                        className="text-primary hover:underline ml-1"
                        onClick={() => onStockClick(sym)}
                      >
                        {sym}
                      </button>
                    ))}
                  </span>
                )}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function HoldingsNewsSection({
  holdingsNews,
  onStockClick,
}: {
  holdingsNews: Record<string, HoldingsNewsItem[]>
  onStockClick: (sym: string) => void
}) {
  const entries = Object.entries(holdingsNews).filter(([, items]) => items.length > 0)
  if (entries.length === 0) return null

  return (
    <div className="space-y-1.5">
      <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
        持仓相关
      </p>
      {entries.slice(0, 5).map(([symbol, items]) => (
        <div key={symbol} className="text-xs">
          <button
            className="font-medium text-primary hover:underline"
            onClick={() => onStockClick(symbol)}
          >
            {symbol}
          </button>
          <span className="text-muted-foreground ml-1">({items.length} 条)</span>
          <div className="ml-3 mt-0.5 space-y-0.5">
            {items.slice(0, 2).map((item, i) => (
              <div key={i} className="flex items-center gap-1 text-[11px] text-muted-foreground">
                <span
                  className="text-[10px]"
                  style={{ color: SENTIMENT_COLOR[item.sentiment] ?? "var(--color-market-flat)" }}
                >
                  <TrendArrow direction={item.sentiment === "positive" ? "up" : item.sentiment === "negative" ? "down" : "neutral"} size={10} />
                </span>
                <span className="truncate">{item.title}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function GlobalSummarySection({
  snapshot,
}: {
  snapshot: {
    indices: { name: string; pct_change: number | null }[]
    commodities: { name: string; pct_change: number | null }[]
    currencies: { name: string; price: number | null }[]
  }
}) {
  const indices = snapshot.indices ?? []
  if (indices.length === 0) return null

  return (
    <div className="space-y-1">
      <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider flex items-center gap-1">
        <Globe className="h-3 w-3" /> 全球联动
      </p>
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[10px]">
        {indices.slice(0, 6).map((idx) => {
          const pct = idx.pct_change ?? 0
          const color = pct > 0 ? "var(--color-market-up)" : pct < 0 ? "var(--color-market-down)" : "var(--color-market-flat)"
          return (
            <span key={idx.name} className="font-mono">
              {idx.name}{" "}
              <span style={{ color }}>{pct > 0 ? "+" : ""}{pct.toFixed(2)}%</span>
            </span>
          )
        })}
      </div>
    </div>
  )
}

function AISentimentSection({ report }: { report: { core_trends?: { topic: string; sentiment: string; summary: string }[]; overall_outlook?: string; sector_outlook?: { bullish?: string[]; bearish?: string[] }; risk_alerts?: { title: string; severity: string }[] } }) {
  return (
    <div className="space-y-2 border-t pt-2">
      <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider flex items-center gap-1">
        <Shield className="h-3 w-3" /> AI 研判
      </p>

      {/* Core trends */}
      {report.core_trends && report.core_trends.length > 0 && (
        <div className="space-y-1">
          {report.core_trends.slice(0, 3).map((trend, i) => {
            const Icon = trend.sentiment === "positive" ? TrendingUp : trend.sentiment === "negative" ? TrendingDown : Minus
            const color = SENTIMENT_COLOR[trend.sentiment] ?? "var(--color-market-flat)"
            return (
              <div key={i} className="flex items-start gap-1.5 text-[11px]">
                <Icon className="h-3 w-3 mt-0.5 shrink-0" style={{ color }} />
                <div>
                  <span className="font-medium">{trend.topic}</span>
                  {trend.summary && (
                    <span className="text-muted-foreground ml-1">{trend.summary}</span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Sector outlook */}
      {report.sector_outlook && (
        <div className="flex flex-wrap gap-1">
          {(report.sector_outlook.bullish ?? []).slice(0, 3).map((s) => (
            <Badge key={s} variant="outline" className="text-[8px] text-market-up border-market-up/30">
              ↑ {s}
            </Badge>
          ))}
          {(report.sector_outlook.bearish ?? []).slice(0, 3).map((s) => (
            <Badge key={s} variant="outline" className="text-[8px] text-market-down border-market-down/30">
              ↓ {s}
            </Badge>
          ))}
        </div>
      )}

      {/* Risk alerts */}
      {report.risk_alerts && report.risk_alerts.length > 0 && (
        <div className="text-[10px] text-muted-foreground">
          <span className="text-warning font-medium">风险: </span>
          {report.risk_alerts.map((a) => a.title).join(" | ")}
        </div>
      )}

      {/* Overall */}
      {report.overall_outlook && (
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          {report.overall_outlook}
        </p>
      )}
    </div>
  )
}
