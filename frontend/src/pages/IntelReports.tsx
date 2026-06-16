/** Intel Reports page — display intelligence-driven analysis reports.
 *
 * Shows report cards with signal indicators, expandable details,
 * and deep analysis entry point.
 *
 * Per PRD v25.0 FR-IA006/007.
 */

import { useState } from "react"
import { formatTime } from "@/lib/formatters"
import { toast } from "sonner"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import {
  FileBarChart,
  ChevronDown,
  ChevronUp,
  Trash2,
  MessageSquare,
  Loader2,
  TrendingUp,
  TrendingDown,
  Minus,
  Eye,
  Filter,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useReports, useReportUnreadCount, useMarkReportRead, useDeleteReport, useCreateChatFromReport } from "@/hooks/useIntelReports"
import { useChatStore } from "@/stores/chatStore"
import type { IntelReport } from "@/types/intel-report"

const SIGNAL_CONFIG = {
  bullish: { label: "看多", color: "text-market-up", bg: "bg-market-up/10", icon: TrendingUp },
  bearish: { label: "看空", color: "text-market-down", bg: "bg-market-down/10", icon: TrendingDown },
  neutral: { label: "中性", color: "text-muted-foreground", bg: "bg-muted", icon: Minus },
} as const

const ACTION_CONFIG: Record<string, { label: string; variant: "default" | "secondary" | "destructive" | "outline" }> = {
  buy: { label: "买入", variant: "default" },
  sell: { label: "卖出", variant: "destructive" },
  hold: { label: "持有", variant: "secondary" },
  watch: { label: "观望", variant: "outline" },
}


function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const color = pct >= 70 ? "bg-market-up" : pct >= 40 ? "bg-yellow-500" : "bg-market-down"
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 rounded-full bg-muted overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] text-muted-foreground">{pct}%</span>
    </div>
  )
}

function ReportCard({
  report,
  expanded,
  onToggle,
  onMarkRead,
  onDelete,
  onDeepAnalysis,
  deepAnalysisLoading,
}: {
  report: IntelReport
  expanded: boolean
  onToggle: () => void
  onMarkRead: () => void
  onDelete: () => void
  onDeepAnalysis: () => void
  deepAnalysisLoading?: boolean
}) {
  const signal = SIGNAL_CONFIG[report.signal] ?? SIGNAL_CONFIG.neutral
  const action = ACTION_CONFIG[report.action] ?? ACTION_CONFIG.hold
  const SignalIcon = signal.icon

  return (
    <Card
      className={`transition-all ${!report.is_read ? "border-l-2 border-l-primary" : ""}`}
    >
      <div
        className="flex items-start gap-3 p-4 cursor-pointer hover:bg-accent/30 transition-colors"
        onClick={() => {
          onToggle()
          if (!report.is_read) onMarkRead()
        }}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            onToggle()
            if (!report.is_read) onMarkRead()
          }
        }}
      >
        <div className={`mt-0.5 rounded-full p-2 shrink-0 ${signal.bg}`}>
          <SignalIcon className={`h-4 w-4 ${signal.color}`} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium">
              {report.is_macro ? "宏观事件分析" : `${report.stock_name}(${report.symbol})`}
            </span>
            <Badge variant={action.variant} className="text-[10px] px-1.5 py-0">
              {action.label}
            </Badge>
            <Badge variant="outline" className={`text-[10px] px-1.5 py-0 ${signal.color}`}>
              {signal.label}
            </Badge>
            {!report.is_read && (
              <span className="h-2 w-2 rounded-full bg-primary shrink-0" />
            )}
          </div>
          <div className="text-xs text-muted-foreground mt-1 line-clamp-2 prose prose-sm dark:prose-invert max-w-none prose-p:my-0">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{report.summary}</ReactMarkdown>
          </div>
          <div className="flex items-center gap-3 mt-1.5">
            <ConfidenceBar value={report.confidence} />
            <span className="text-[10px] text-muted-foreground">
              {report.intel_item_ids.length} 条情报
            </span>
            <span className="text-[10px] text-muted-foreground">
              {formatTime(report.created_at)}
            </span>
          </div>
        </div>
        <div className="shrink-0 mt-1">
          {expanded ? (
            <ChevronUp className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          )}
        </div>
      </div>

      {expanded && (
        <CardContent className="pt-0 pb-4 px-4 space-y-4 border-t">
          {/* Factors */}
          {report.factors.length > 0 && (
            <div>
              <h4 className="text-xs font-medium mb-2">影响因子</h4>
              <div className="space-y-1.5">
                {report.factors.map((f, i) => {
                  const impactColor =
                    f.impact === "positive"
                      ? "text-market-up"
                      : f.impact === "negative"
                        ? "text-market-down"
                        : "text-muted-foreground"
                  return (
                    <div key={i} className="flex items-start gap-2 text-xs">
                      <Badge variant="outline" className="text-[9px] shrink-0 px-1 py-0">
                        {f.category}
                      </Badge>
                      <span className={`shrink-0 ${impactColor}`}>
                        {f.impact === "positive" ? "+" : f.impact === "negative" ? "-" : "~"}
                      </span>
                      <div className="h-1 w-8 rounded-full bg-muted mt-1.5 shrink-0 overflow-hidden">
                        <div className="h-full rounded-full bg-primary" style={{ width: `${f.weight * 100}%` }} />
                      </div>
                      <span className="text-muted-foreground">{f.description}</span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Position Context */}
          {report.position_context && (
            <div className="rounded-lg bg-accent/50 p-3">
              <h4 className="text-xs font-medium mb-1.5">持仓建议</h4>
              <div className="text-xs text-muted-foreground prose prose-sm dark:prose-invert max-w-none prose-p:my-0">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{report.position_context.advice}</ReactMarkdown>
              </div>
              {report.position_context.key_levels && (
                <div className="flex gap-4 mt-1.5 text-[10px] text-muted-foreground">
                  <span>支撑: {report.position_context.key_levels.support}</span>
                  <span>压力: {report.position_context.key_levels.resistance}</span>
                </div>
              )}
            </div>
          )}

          {/* Risk Warnings */}
          {report.risk_warnings.length > 0 && (
            <div>
              <h4 className="text-xs font-medium mb-1.5">风险提示</h4>
              <div className="flex flex-wrap gap-1.5">
                {report.risk_warnings.map((w, i) => (
                  <Badge key={i} variant="outline" className="text-[10px] text-yellow-600 border-yellow-300">
                    {w}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {/* Outlook */}
          {report.outlook && (
            <div>
              <h4 className="text-xs font-medium mb-1">展望</h4>
              <div className="text-xs text-muted-foreground prose prose-sm dark:prose-invert max-w-none prose-p:my-0">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{report.outlook}</ReactMarkdown>
              </div>
            </div>
          )}

          {/* Reasoning */}
          {report.reasoning.length > 0 && (
            <div>
              <h4 className="text-xs font-medium mb-1.5">推理链</h4>
              <ol className="list-decimal list-inside space-y-0.5">
                {report.reasoning.map((r, i) => (
                  <li key={i} className="text-xs text-muted-foreground">{r}</li>
                ))}
              </ol>
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center gap-2 pt-2">
            <Button
              size="sm"
              variant="default"
              className="gap-1.5 text-xs"
              disabled={deepAnalysisLoading}
              onClick={(e) => {
                e.stopPropagation()
                onDeepAnalysis()
              }}
            >
              {deepAnalysisLoading ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <MessageSquare className="h-3 w-3" />
              )}
              {deepAnalysisLoading ? "准备中..." : "深度分析"}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="gap-1 text-xs text-muted-foreground"
              onClick={(e) => {
                e.stopPropagation()
                onDelete()
              }}
            >
              <Trash2 className="h-3 w-3" />
              删除
            </Button>
            <span className="flex-1" />
            <span className="text-[10px] text-muted-foreground">
              {report.model_used}
            </span>
          </div>
        </CardContent>
      )}
    </Card>
  )
}

export default function IntelReports() {
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [symbolFilter, setSymbolFilter] = useState<string>("all")
  const [showUnreadOnly, setShowUnreadOnly] = useState(false)
  const [showMacroOnly, setShowMacroOnly] = useState(false)
  const [deepAnalysisId, setDeepAnalysisId] = useState<string | null>(null)

  const { data: unreadCount } = useReportUnreadCount()
  const { data, isLoading } = useReports({
    symbol: showMacroOnly ? "MACRO" : (symbolFilter === "all" ? undefined : symbolFilter),
    unread_only: showUnreadOnly || undefined,
    limit: 50,
  })
  const markRead = useMarkReportRead()
  const deleteReportMutation = useDeleteReport()
  const createChat = useCreateChatFromReport()

  const { loadThread, openChat, sendMessage } = useChatStore()

  const reports = data?.reports ?? []

  // Extract unique symbols for filter
  const uniqueSymbols = [...new Set(reports.map((r) => r.symbol))].sort()

  const handleDeepAnalysis = (report: IntelReport) => {
    // Already has a thread — just open it in the chat sheet
    if (report.thread_id) {
      loadThread(report.thread_id)
      openChat()
      return
    }

    setDeepAnalysisId(report.id)
    createChat.mutate(report.id, {
      onSuccess: async ({ thread_id, initial_message }) => {
        // Load the empty thread and open the chat sheet
        await loadThread(thread_id)
        openChat()
        setDeepAnalysisId(null)
        // Send initial message via chat store (shows loading spinner)
        if (initial_message) {
          sendMessage(initial_message)
        }
      },
      onError: () => {
        setDeepAnalysisId(null)
        toast.error("创建深度分析失败，请稍后重试")
      },
    })
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FileBarChart className="h-5 w-5 text-primary" />
          <h1 className="text-lg font-bold">情报分析</h1>
          {(unreadCount ?? 0) > 0 && (
            <Badge variant="default" className="text-[10px]">
              {unreadCount} 未读
            </Badge>
          )}
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1.5">
          <Filter className="h-3.5 w-3.5 text-muted-foreground" />
          <Select value={symbolFilter} onValueChange={setSymbolFilter}>
            <SelectTrigger className="h-8 w-36 text-xs">
              <SelectValue placeholder="全部股票" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部股票</SelectItem>
              {uniqueSymbols.map((sym) => (
                <SelectItem key={sym} value={sym}>{sym}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button
          variant={showMacroOnly ? "default" : "outline"}
          size="sm"
          className="h-8 text-xs gap-1"
          onClick={() => {
            setShowMacroOnly(!showMacroOnly)
            if (!showMacroOnly) setSymbolFilter("all")
          }}
        >
          宏观
        </Button>
        <Button
          variant={showUnreadOnly ? "default" : "outline"}
          size="sm"
          className="h-8 text-xs gap-1"
          onClick={() => setShowUnreadOnly(!showUnreadOnly)}
        >
          <Eye className="h-3 w-3" />
          仅未读
        </Button>
      </div>

      {/* Report List */}
      {isLoading ? (
        <div className="py-12 text-center text-sm text-muted-foreground">加载中...</div>
      ) : reports.length === 0 ? (
        <div className="py-12 text-center text-sm text-muted-foreground">
          暂无分析报告。当情报中心检测到与持仓相关的情报时，将自动生成分析报告。
        </div>
      ) : (
        <div className="space-y-2">
          {reports.map((report) => (
            <ReportCard
              key={report.id}
              report={report}
              expanded={expandedId === report.id}
              onToggle={() => setExpandedId(expandedId === report.id ? null : report.id)}
              onMarkRead={() => markRead.mutate(report.id)}
              onDelete={() => deleteReportMutation.mutate(report.id)}
              onDeepAnalysis={() => handleDeepAnalysis(report)}
              deepAnalysisLoading={deepAnalysisId === report.id}
            />
          ))}
        </div>
      )}
    </div>
  )
}
