import {
  Check,
  X,
  Clock,
  BarChart3,
  Brain,
  AlertTriangle,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useReview } from "@/hooks/useActions"
import { cn } from "@/lib/utils"
import type { DecisionOutcome, MissedOpportunity } from "@/types/action"

// ---------------------------------------------------------------------------
// Decision Outcome Card
// ---------------------------------------------------------------------------

const resultConfig = {
  correct: { icon: Check, color: "text-green-500", bg: "bg-green-500/10", label: "正确" },
  wrong: { icon: X, color: "text-red-500", bg: "bg-red-500/10", label: "错误" },
  pending: { icon: Clock, color: "text-yellow-500", bg: "bg-yellow-500/10", label: "待定" },
} as const

function DecisionCard({ decision }: { decision: DecisionOutcome }) {
  const cfg = resultConfig[decision.result] ?? resultConfig.pending
  const Icon = cfg.icon

  return (
    <div className="flex items-center gap-3 rounded-lg border px-3 py-2.5">
      <div className={cn("flex h-7 w-7 items-center justify-center rounded-md shrink-0", cfg.bg)}>
        <Icon className={cn("h-3.5 w-3.5", cfg.color)} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium truncate">{decision.stock_name}</span>
          <span className="text-xs text-muted-foreground">{decision.action}</span>
        </div>
        <p className="text-xs text-muted-foreground truncate">{decision.reason}</p>
      </div>
      {decision.pnl != null && (
        <span
          className={cn(
            "text-sm font-numeric shrink-0",
            decision.pnl > 0 ? "text-green-500" : decision.pnl < 0 ? "text-red-500" : "",
          )}
        >
          {decision.pnl > 0 ? "+" : ""}
          {decision.pnl.toFixed(0)}
        </span>
      )}
      <Badge variant="outline" className={cn("text-[10px] shrink-0", cfg.color)}>
        {cfg.label}
      </Badge>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Missed Opportunity Card
// ---------------------------------------------------------------------------

function MissedCard({ item }: { item: MissedOpportunity }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-dashed px-3 py-2.5">
      <AlertTriangle className="h-4 w-4 text-yellow-500 shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">{item.stock_name}</span>
          <span className="text-xs text-muted-foreground">{item.symbol}</span>
        </div>
        <p className="text-xs text-muted-foreground truncate">{item.description}</p>
      </div>
      <span className="text-sm font-numeric text-yellow-500 shrink-0">
        +{item.potential_pnl_pct.toFixed(1)}%
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Stats Cards
// ---------------------------------------------------------------------------

function StatCard({
  label,
  value,
  sub,
  color,
}: {
  label: string
  value: string
  sub?: string
  color?: string
}) {
  return (
    <Card>
      <CardContent className="py-3 px-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className={cn("text-lg font-bold font-numeric mt-0.5", color)}>{value}</p>
        {sub && <p className="text-[10px] text-muted-foreground">{sub}</p>}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Review Page
// ---------------------------------------------------------------------------

export default function Review() {
  const { data: review, isLoading, error } = useReview()

  if (isLoading) {
    return (
      <div className="space-y-5">
        <Skeleton className="h-8 w-32" />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Skeleton className="h-20 rounded-lg" />
          <Skeleton className="h-20 rounded-lg" />
          <Skeleton className="h-20 rounded-lg" />
          <Skeleton className="h-20 rounded-lg" />
        </div>
        <Skeleton className="h-40 rounded-lg" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="space-y-5">
        <h1 className="text-headline">复盘</h1>
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          复盘数据加载失败: {error.message}
        </div>
      </div>
    )
  }

  if (!review) {
    return (
      <div className="space-y-5">
        <h1 className="text-headline">复盘</h1>
        <Card>
          <CardContent className="py-8 text-center">
            <BarChart3 className="h-8 w-8 mx-auto text-muted-foreground/40 mb-2" />
            <p className="text-sm text-muted-foreground">暂无复盘数据</p>
            <p className="text-xs text-muted-foreground/60 mt-1">
              交易日结束后将自动生成当日复盘报告
            </p>
          </CardContent>
        </Card>
      </div>
    )
  }

  const correctCount = review.decisions.filter((d) => d.result === "correct").length
  const wrongCount = review.decisions.filter((d) => d.result === "wrong").length
  const pendingCount = review.decisions.filter((d) => d.result === "pending").length
  const totalDecisions = review.decisions.length
  const winRate = totalDecisions > 0 ? ((correctCount / totalDecisions) * 100).toFixed(0) : "--"

  return (
    <div className="space-y-5">
      {/* Header */}
      <div>
        <h1 className="text-headline">复盘</h1>
        <p className="text-caption text-muted-foreground mt-0.5">
          {review.date} 交易回顾
        </p>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          label="今日盈亏"
          value={`${review.daily_pnl > 0 ? "+" : ""}${review.daily_pnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
          sub={`${review.daily_pnl_pct > 0 ? "+" : ""}${review.daily_pnl_pct.toFixed(2)}%`}
          color={review.daily_pnl > 0 ? "text-green-500" : review.daily_pnl < 0 ? "text-red-500" : undefined}
        />
        <StatCard
          label="胜率"
          value={`${winRate}%`}
          sub={`${correctCount}胜 ${wrongCount}负 ${pendingCount}待定`}
        />
        <StatCard
          label="30日信号准确率"
          value={`${(review.signal_accuracy_30d * 100).toFixed(1)}%`}
          sub="过去30个交易日"
        />
        <StatCard
          label="Brier 校准分"
          value={review.brier_score.toFixed(3)}
          sub={review.brier_score < 0.2 ? "校准良好" : review.brier_score < 0.3 ? "尚可" : "需改进"}
          color={review.brier_score < 0.2 ? "text-green-500" : review.brier_score < 0.3 ? "text-yellow-500" : "text-red-500"}
        />
      </div>

      {/* Decision Outcomes */}
      <Card>
        <CardHeader className="py-3 px-4">
          <CardTitle className="text-title flex items-center gap-2">
            <BarChart3 className="h-4 w-4 text-primary" />
            决策结果
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          {review.decisions.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-4">今日无决策记录</p>
          ) : (
            <div className="space-y-2">
              {review.decisions.map((d) => (
                <DecisionCard key={d.id} decision={d} />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Missed Opportunities */}
      {review.missed_opportunities.length > 0 && (
        <Card>
          <CardHeader className="py-3 px-4">
            <CardTitle className="text-title flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-yellow-500" />
              错过的机会
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <div className="space-y-2">
              {review.missed_opportunities.map((m, i) => (
                <MissedCard key={i} item={m} />
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* AI Summary */}
      {review.ai_summary && (
        <Card>
          <CardHeader className="py-3 px-4">
            <CardTitle className="text-title flex items-center gap-2">
              <Brain className="h-4 w-4 text-primary" />
              AI 总结
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-sm text-muted-foreground leading-relaxed whitespace-pre-line">
              {review.ai_summary}
            </p>
          </CardContent>
        </Card>
      )}

      {/* Disclaimer */}
      <div className="rounded-lg border border-dashed p-3">
        <p className="text-xs text-muted-foreground leading-relaxed">
          <strong>说明：</strong>复盘数据由 AI 自动生成，仅供参考。信号准确率和 Brier 校准分基于历史数据统计，不代表未来表现。
        </p>
      </div>
    </div>
  )
}
