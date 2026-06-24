/** Recommendation detail dialog — full display with outcomes and deep analysis link.
 *
 * Per PRD v28.0 FR-REC061: Detail expansion dialog.
 */

import { useNavigate } from "react-router-dom"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Target,
  ShieldAlert,
  TrendingUp,
  DollarSign,
  MessageSquare,
  Sparkles,
  ShoppingCart,
  Activity,
  AlertTriangle,
} from "lucide-react"
import { useChatStore } from "@/stores/chatStore"
import type { Recommendation } from "@/types/recommendation"

interface RecommendationDetailDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  rec: Recommendation | null
  onBuy?: (rec: Recommendation) => void
}

const CONFIDENCE_STYLES: Record<string, string> = {
  high: "bg-market-up/15 text-market-up border-market-up/30",
  medium: "bg-yellow-500/15 text-yellow-600 border-yellow-500/30",
  low: "bg-muted text-muted-foreground border-muted",
}
const CONFIDENCE_LABELS: Record<string, string> = {
  high: "高置信",
  medium: "中置信",
  low: "低置信",
}

const SESSION_LABELS: Record<string, string> = {
  pre_market: "盘前",
  early: "早盘",
  mid: "盘中",
  late: "尾盘",
  post_market: "盘后",
}

const STYLE_LABELS: Record<string, string> = {
  value: "价值投资",
  growth: "成长投资",
  momentum: "动量交易",
  swing: "波段交易",
  dividend: "红利收息",
  sector: "板块轮动",
}

function OutcomeRow({
  label,
  price,
  change,
  correct,
}: {
  label: string
  price: number | null
  change: number | null
  correct: number | null
}) {
  if (price == null) {
    return (
      <div className="flex items-center justify-between py-1.5 text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="text-muted-foreground">--</span>
      </div>
    )
  }

  const isUp = (change ?? 0) > 0
  const color = isUp ? "text-market-up" : "text-market-down"
  const prefix = isUp ? "+" : ""

  return (
    <div className="flex items-center justify-between py-1.5 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <div className="flex items-center gap-2">
        <span className="font-numeric">{price.toFixed(2)}</span>
        <span className={`font-numeric ${color}`}>
          {prefix}{change?.toFixed(2)}%
        </span>
        {correct != null && (
          <Badge
            variant="outline"
            className={`text-[9px] px-1 py-0 ${correct ? "border-market-up/30 text-market-up" : "border-market-down/30 text-market-down"}`}
          >
            {correct ? "正确" : "偏差"}
          </Badge>
        )}
      </div>
    </div>
  )
}

export function RecommendationDetailDialog({
  open,
  onOpenChange,
  rec,
  onBuy,
}: RecommendationDetailDialogProps) {
  const navigate = useNavigate()
  const openChatWithContext = useChatStore((s) => s.openChatWithContext)

  if (!rec) return null

  const scorePct = Math.round(rec.score * 100)
  const isCrossSector = rec.factors?.cross_sector_discovery === 1.0
  const outcomes = rec.outcomes

  // Top 5 factors by value
  const topFactors = Object.entries(rec.factors || {})
    .filter(([k]) => k !== "cross_sector_discovery" && k !== "session_boost")
    .sort(([, a], [, b]) => b - a)
    .slice(0, 5)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {rec.name}
            <span className="text-sm text-muted-foreground font-normal">{rec.symbol}</span>
            <span
              className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold ${
                scorePct >= 80
                  ? "bg-market-up/15 text-market-up border-market-up/30"
                  : scorePct >= 65
                    ? "bg-yellow-500/15 text-yellow-600 border-yellow-500/30"
                    : "bg-muted text-muted-foreground"
              }`}
            >
              {scorePct}分
            </span>
            <span
              className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${CONFIDENCE_STYLES[rec.confidence] ?? CONFIDENCE_STYLES.medium}`}
            >
              {CONFIDENCE_LABELS[rec.confidence] ?? rec.confidence}
            </span>
            {rec.ai_analyzed === false && (
              <Badge variant="outline" className="text-[10px] border-orange-500/30 text-orange-600 bg-orange-500/15">
                未经AI审核
              </Badge>
            )}
            {isCrossSector && (
              <Badge variant="outline" className="text-[10px] border-info/30 text-info">
                跨行业发现
              </Badge>
            )}
          </DialogTitle>
          <DialogDescription className="sr-only">
            推荐详情: {rec.name} ({rec.symbol})
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5">
          {/* Metadata row */}
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <Badge variant="outline" className="text-[10px]">
              {STYLE_LABELS[rec.style] || rec.style}
            </Badge>
            <Badge variant="outline" className="text-[10px]">
              {SESSION_LABELS[rec.session] || rec.session}
            </Badge>
            <span>{new Date(rec.created_at).toLocaleString("zh-CN")}</span>
          </div>

          {/* Current / closing price indicator */}
          {rec.current_price != null && (
            <div className={`rounded-lg border p-3 ${
              rec.price_vs_entry != null && Math.abs(rec.price_vs_entry) >= 5
                ? "border-orange-500/30 bg-orange-500/5"
                : "border-info/30 bg-info/5"
            }`}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Activity className="h-4 w-4 text-info" />
                  <span className="text-xs font-medium">
                    {rec.market_open ? "实时价格" : "收盘价格"}
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-lg font-semibold font-numeric">
                    {rec.current_price.toFixed(2)}
                  </span>
                  {rec.current_pct_change != null && (
                    <span
                      className={`text-sm font-numeric font-medium ${rec.current_pct_change >= 0 ? "text-market-up" : "text-market-down"}`}
                    >
                      {rec.current_pct_change >= 0 ? "+" : ""}
                      {rec.current_pct_change.toFixed(2)}%
                    </span>
                  )}
                  {rec.price_vs_entry != null && (
                    <Badge
                      variant="outline"
                      className={`font-numeric ${rec.price_vs_entry >= 0 ? "border-market-up/30 text-market-up" : "border-market-down/30 text-market-down"}`}
                    >
                      较介入 {rec.price_vs_entry >= 0 ? "+" : ""}
                      {rec.price_vs_entry.toFixed(2)}%
                    </Badge>
                  )}
                </div>
              </div>
              {rec.price_vs_entry != null && Math.abs(rec.price_vs_entry) >= 5 && (
                <div className="flex items-center gap-1.5 mt-2 text-xs text-orange-600">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  当前价格已大幅偏离介入价，建议重新评估买入时机
                </div>
              )}
            </div>
          )}

          {/* Price targets */}
          {(rec.entry_price || rec.target_price || rec.stop_loss) && (
            <div className="grid grid-cols-3 gap-3">
              {rec.entry_price && (
                <div className="rounded-lg bg-muted/50 p-3 text-center">
                  <div className="text-[10px] text-muted-foreground flex items-center justify-center gap-1">
                    <DollarSign className="h-3 w-3 text-primary" />
                    介入价
                  </div>
                  <div className="text-sm font-semibold font-numeric mt-1">
                    {rec.entry_price.toFixed(2)}
                  </div>
                </div>
              )}
              {rec.target_price && (
                <div className="rounded-lg bg-muted/50 p-3 text-center">
                  <div className="text-[10px] text-muted-foreground flex items-center justify-center gap-1">
                    <Target className="h-3 w-3 text-market-up" />
                    目标价
                  </div>
                  <div className="text-sm font-semibold font-numeric mt-1 text-market-up">
                    {rec.target_price.toFixed(2)}
                  </div>
                </div>
              )}
              {rec.stop_loss && (
                <div className="rounded-lg bg-muted/50 p-3 text-center">
                  <div className="text-[10px] text-muted-foreground flex items-center justify-center gap-1">
                    <ShieldAlert className="h-3 w-3 text-market-down" />
                    止损价
                  </div>
                  <div className="text-sm font-semibold font-numeric mt-1 text-market-down">
                    {rec.stop_loss.toFixed(2)}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Reason */}
          {rec.reason && (
            <div className="space-y-1">
              <div className="flex items-center gap-1.5 text-xs font-medium">
                <TrendingUp className="h-3.5 w-3.5 text-market-up" />
                推荐理由
                {rec.ai_analyzed === false && (
                  <span className="text-[10px] text-orange-600 font-normal">(量化筛选)</span>
                )}
              </div>
              <p className="text-sm text-foreground/80 leading-relaxed">{rec.reason}</p>
            </div>
          )}

          {/* Risk notes */}
          {rec.risk_notes && (
            <div className="space-y-1">
              <div className="flex items-center gap-1.5 text-xs font-medium">
                <ShieldAlert className="h-3.5 w-3.5 text-yellow-500" />
                风险提示
              </div>
              <p className="text-sm text-muted-foreground leading-relaxed">
                {rec.risk_notes}
              </p>
            </div>
          )}

          {/* Key factors */}
          {topFactors.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center gap-1.5 text-xs font-medium">
                <Sparkles className="h-3.5 w-3.5 text-primary" />
                关键因子
              </div>
              <div className="space-y-1">
                {topFactors.map(([name, value]) => (
                  <div key={name} className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground w-28 truncate">
                      {name}
                    </span>
                    <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
                      <div
                        className="h-full rounded-full bg-primary transition-all"
                        style={{ width: `${Math.min(value * 100, 100)}%` }}
                      />
                    </div>
                    <span className="text-xs font-numeric w-10 text-right">
                      {(value * 100).toFixed(0)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* T+N Outcomes */}
          {outcomes && (
            <div className="space-y-2">
              <div className="text-xs font-medium">实际表现</div>
              <div className="rounded-lg border p-3 space-y-0.5">
                <OutcomeRow
                  label="T+1"
                  price={outcomes.actual_price_t1}
                  change={outcomes.actual_change_t1}
                  correct={outcomes.correct_t1}
                />
                <OutcomeRow
                  label="T+3"
                  price={outcomes.actual_price_t3}
                  change={outcomes.actual_change_t3}
                  correct={outcomes.correct_t3}
                />
                <OutcomeRow
                  label="T+5"
                  price={outcomes.actual_price_t5}
                  change={outcomes.actual_change_t5}
                  correct={outcomes.correct_t5}
                />
                <OutcomeRow
                  label="T+10"
                  price={outcomes.actual_price_t10}
                  change={outcomes.actual_change_t10}
                  correct={outcomes.correct_t10}
                />
              </div>
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-2 pt-2">
            {onBuy && (
              <Button
                size="sm"
                className="bg-market-up hover:bg-market-up/90 text-white"
                onClick={() => {
                  onOpenChange(false)
                  onBuy(rec)
                }}
              >
                <ShoppingCart className="h-3.5 w-3.5 mr-1.5" />
                买入
              </Button>
            )}
            <Button
              size="sm"
              variant={onBuy ? "outline" : "default"}
              onClick={() => {
                onOpenChange(false)
                openChatWithContext(
                  { symbol: rec.symbol, mode: "stock" },
                  `帮我深度分析一下 ${rec.name}(${rec.symbol})，该股被智能选股系统推荐，综合评分 ${scorePct} 分，推荐理由：${rec.reason || "暂无"}`,
                )
              }}
            >
              <MessageSquare className="h-3.5 w-3.5 mr-1.5" />
              发送到 Agent 深度分析
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                onOpenChange(false)
                navigate(`/stock/${rec.symbol}`)
              }}
            >
              查看个股详情
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
