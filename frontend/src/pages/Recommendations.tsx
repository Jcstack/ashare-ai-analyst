/** Recommendations page — smart stock recommendation display.
 *
 * Shows style-filtered recommendation cards with session indicators,
 * score badges, dismiss functionality, detail dialog, and performance tab.
 *
 * Per PRD v28.0 Smart Stock Recommendation System.
 */

import { useState, useEffect, useRef } from "react"
import { Sparkles, RefreshCw, AlertTriangle, BarChart3, List, Loader2 } from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Button } from "@/components/ui/button"
import { RecommendationCard } from "@/components/recommendations/RecommendationCard"
import { RecommendationDetailDialog } from "@/components/recommendations/RecommendationDetailDialog"
import { PerformanceDashboard } from "@/components/recommendations/PerformanceDashboard"
import { StylePreferences } from "@/components/recommendations/StylePreferences"
import { TradeDialog } from "@/components/trade/TradeDialog"
import type { TradeContext } from "@/components/trade/TradeDialog"
import {
  useTodayRecommendations,
  useDismissRecommendation,
  useStyles,
  useRefreshRecommendations,
  useRefreshStatus,
} from "@/hooks/useRecommendations"
import { useMarketStatus } from "@/hooks/useMarketStatus"
import type { MarketStatus } from "@/types/market"
import { useQueryClient } from "@tanstack/react-query"
import type { Recommendation } from "@/types/recommendation"

function getSessionLabel(status: MarketStatus | undefined): string {
  if (!status) return "加载中"
  switch (status.status) {
    case "trading":
      return "盘中"
    case "lunch":
      return "午间休市"
    case "pre_market":
      return "盘前"
    case "closed":
      return "已收市"
    case "holiday":
      return status.holiday_info ? `${status.holiday_info.name}休市` : "休市"
    case "emergency":
      return "临时停市"
    default:
      return status.label || "休市"
  }
}

function buildEmptyReasonMessage(reason: string | null): string {
  switch (reason) {
    case "no_candidates":
      return "市场筛选未找到符合条件的股票"
    case "all_rejected":
      return "候选股票未通过AI审核"
    default:
      return "未生成推荐结果"
  }
}

type Tab = "list" | "performance"

export default function Recommendations() {
  const [selectedStyle, setSelectedStyle] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<Tab>("list")
  const [detailRec, setDetailRec] = useState<Recommendation | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [tradeDialogOpen, setTradeDialogOpen] = useState(false)
  const [tradeContext, setTradeContext] = useState<TradeContext | null>(null)
  const [activeRunId, setActiveRunId] = useState<string | null>(null)

  const { data: stylesData } = useStyles()
  const {
    data: recsData,
    isLoading,
    isFetching,
  } = useTodayRecommendations(selectedStyle ?? undefined)
  const dismiss = useDismissRecommendation()
  const refresh = useRefreshRecommendations()

  const { data: runStatus } = useRefreshStatus(activeRunId)
  const queryClient = useQueryClient()

  const { data: marketStatus } = useMarketStatus()

  const styles = stylesData?.styles ?? []
  const recs = recsData?.items ?? []
  const sessionLabel = getSessionLabel(marketStatus)
  const isRunning = !!activeRunId && runStatus?.status === "running"

  // Track previous status to detect transitions
  const prevStatusRef = useRef<string | undefined>(undefined)
  const pollStartRef = useRef(Date.now())

  // Reset poll timer when a new run starts
  useEffect(() => {
    if (activeRunId) pollStartRef.current = Date.now()
  }, [activeRunId])

  useEffect(() => {
    const prevStatus = prevStatusRef.current
    const curStatus = runStatus?.status
    prevStatusRef.current = curStatus

    if (!curStatus || !activeRunId || curStatus === prevStatus) return

    if (curStatus === "completed") {
      setActiveRunId(null)
      queryClient.invalidateQueries({ queryKey: ["recommendations"] })
      queryClient.invalidateQueries({ queryKey: ["recommendations-today"] })
      queryClient.invalidateQueries({ queryKey: ["recommendation-count"] })

      const total = runStatus.total_recs ?? 0
      if (total > 0) {
        toast.success(`已生成 ${total} 条新推荐`)
      } else {
        // Build message from per-style details
        const details = runStatus.style_details
        if (details) {
          const reasons = Object.values(details)
            .filter((d) => d.status === "empty" && d.reason)
            .map((d) => buildEmptyReasonMessage(d.reason))
          const msg = [...new Set(reasons)].join("；") || "本轮未生成推荐"
          toast.info(msg)
        } else {
          toast.info("本轮未生成推荐")
        }
      }
    } else if (curStatus === "failed") {
      setActiveRunId(null)
      toast.error(runStatus.error || "推荐生成失败，请稍后重试")
    }
  }, [runStatus, activeRunId, queryClient])

  // Safety: detect polling timeout (status stuck on "running" after 10 min)
  // The hook itself overrides status to "failed" on timeout, but this
  // catches edge cases where the effect above hasn't fired yet.
  useEffect(() => {
    if (!activeRunId || runStatus?.status !== "running") return
    const elapsed = Date.now() - pollStartRef.current
    if (elapsed < 600_000) return
    // Polling has timed out — clear UI state
    setActiveRunId(null)
    toast.error("推荐生成超时，请稍后重试")
  }, [activeRunId, runStatus])

  const handleDismiss = (id: string) => {
    dismiss.mutate(id, {
      onSuccess: () => toast.success("已忽略该推荐"),
    })
  }

  const handleCardClick = (rec: Recommendation) => {
    setDetailRec(rec)
    setDetailOpen(true)
  }

  const handleBuy = (rec: Recommendation) => {
    setTradeContext({
      action: "buy",
      symbol: rec.symbol,
      stockName: rec.name,
      defaultPrice: rec.entry_price ?? undefined,
      recommendationId: rec.id,
    })
    setTradeDialogOpen(true)
  }

  const handleManualRefresh = () => {
    refresh.mutate(undefined, {
      onSuccess: (data) => {
        if (data.status === "accepted" && data.run_id) {
          setActiveRunId(data.run_id)
        } else if (data.status === "ok") {
          toast.success(`已生成 ${data.total ?? 0} 条新推荐`)
        } else if (data.status === "cooldown") {
          toast.info(data.message || "请等待30分钟后再次刷新")
        } else {
          toast.info(data.message || "当前不在交易时段")
        }
      },
      onError: () => toast.error("刷新失败，请稍后重试"),
    })
  }

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-primary" />
          <h1 className="text-lg font-bold">智能选股</h1>
          <Badge variant="outline" className="text-[10px]">
            {sessionLabel}
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          {/* Tab toggles */}
          <div className="flex items-center rounded-lg border p-0.5">
            <button
              onClick={() => setActiveTab("list")}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                activeTab === "list"
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <List className="h-3.5 w-3.5 inline mr-1" />
              推荐列表
            </button>
            <button
              onClick={() => setActiveTab("performance")}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                activeTab === "performance"
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <BarChart3 className="h-3.5 w-3.5 inline mr-1" />
              表现统计
            </button>
          </div>

          {activeTab === "list" && (
            <Button
              variant="outline"
              size="sm"
              onClick={handleManualRefresh}
              disabled={isFetching || refresh.isPending || isRunning}
            >
              <RefreshCw
                className={`h-3.5 w-3.5 mr-1.5 ${isFetching || refresh.isPending || isRunning ? "animate-spin" : ""}`}
              />
              刷新
            </Button>
          )}
        </div>
      </div>

      {activeTab === "list" ? (
        <>
          {/* Style filter tabs */}
          <StylePreferences
            styles={styles}
            selected={selectedStyle}
            onSelect={setSelectedStyle}
          />

          {/* Progress banner */}
          {isRunning && (
            <div className="flex items-center gap-2 rounded-lg border border-primary/20 bg-primary/5 p-3 text-sm">
              <Loader2 className="h-4 w-4 animate-spin text-primary" />
              <span>
                正在生成推荐...
                {runStatus?.style_details && (() => {
                  const details = Object.values(runStatus.style_details!)
                  const done = details.filter(
                    (d) => d.status && d.status !== "running"
                  ).length
                  const total = details.length
                  return total > 0 ? ` (${done}/${total} 风格已完成)` : ""
                })()}
              </span>
            </div>
          )}

          {/* Recommendation cards */}
          {isLoading ? (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-40 rounded-lg" />
              ))}
            </div>
          ) : recs.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <Sparkles className="h-10 w-10 text-muted-foreground/40 mb-3" />
              <p className="text-sm text-muted-foreground">
                {selectedStyle
                  ? "当前风格暂无推荐，请稍后刷新或切换风格"
                  : "今日暂无推荐，系统将在交易时段自动生成"}
              </p>
              <Button
                variant="outline"
                size="sm"
                className="mt-4"
                onClick={handleManualRefresh}
                disabled={refresh.isPending || isRunning}
              >
                <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${refresh.isPending || isRunning ? "animate-spin" : ""}`} />
                立即生成
              </Button>
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {recs.map((rec) => (
                <RecommendationCard
                  key={rec.id}
                  rec={rec}
                  onDismiss={handleDismiss}
                  onClick={handleCardClick}
                  onBuy={handleBuy}
                />
              ))}
            </div>
          )}

          {/* Disclaimer — FR-REC023 */}
          <div className="flex gap-2 rounded-lg border border-yellow-500/20 bg-yellow-500/5 p-3 text-xs text-muted-foreground">
            <AlertTriangle className="h-4 w-4 shrink-0 text-yellow-500 mt-0.5" />
            <p>
              免责声明：以上推荐仅供参考，不构成任何投资建议。股市有风险，投资需谨慎。推荐结果基于量化模型和AI分析，
              不保证准确性和收益。请结合自身风险承受能力和判断做出投资决策。
            </p>
          </div>
        </>
      ) : (
        <PerformanceDashboard />
      )}

      {/* Detail dialog */}
      <RecommendationDetailDialog
        open={detailOpen}
        onOpenChange={setDetailOpen}
        rec={detailRec}
        onBuy={handleBuy}
      />

      {/* Trade dialog (buy from recommendation) */}
      <TradeDialog
        open={tradeDialogOpen}
        onOpenChange={setTradeDialogOpen}
        tradeContext={tradeContext}
      />
    </div>
  )
}
