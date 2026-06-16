/** Agent Brain Dashboard — autonomous trading agent monitor (v34.0). */

import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { Brain, Loader2, Play, TrendingUp, TrendingDown, Activity, Target, BarChart3, ListChecks, Gauge, Shield } from "lucide-react"
import {
  fetchAgentStatus,
  fetchAgentTheses,
  fetchAgentDecisions,
  fetchCalibrationReport,
  triggerAgentCycle,
} from "@/api/agent"
import type {
  AgentStatus,
  InvestmentThesis,
  DecisionOutcome,
  CycleResult,
  CalibrationReport,
} from "@/types/agent"

// ─── Helpers ──────────────────────────────────────────────────────────────────

function pctColor(val: number | null): string {
  if (val == null) return "text-gray-500"
  if (val > 0) return "text-emerald-400"
  if (val < 0) return "text-red-400"
  return "text-gray-400"
}

function fmtPct(val: number | null): string {
  if (val == null) return "--"
  const sign = val > 0 ? "+" : ""
  return `${sign}${val.toFixed(2)}%`
}

function fmtDate(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })
  } catch {
    return iso
  }
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatCard({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: string | number; sub?: string }) {
  return (
    <div className="rounded-xl bg-gray-800/60 border border-gray-700/50 p-5 flex flex-col gap-1">
      <div className="flex items-center gap-2 text-sm text-gray-400">
        {icon}
        {label}
      </div>
      <div className="text-2xl font-bold text-gray-100">{value}</div>
      {sub && <div className="text-xs text-gray-500">{sub}</div>}
    </div>
  )
}

function ConvictionBar({ value }: { value: number }) {
  const clamped = Math.max(0, Math.min(100, value))
  const barColor = clamped >= 70 ? "bg-emerald-500" : clamped >= 40 ? "bg-amber-500" : "bg-red-500"
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 rounded-full bg-gray-700 overflow-hidden">
        <div className={`h-full rounded-full ${barColor}`} style={{ width: `${clamped}%` }} />
      </div>
      <span className="text-xs text-gray-400 w-10 text-right">{clamped}%</span>
    </div>
  )
}

function DirectionBadge({ direction }: { direction: string }) {
  const isBullish = direction === "bullish"
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${
        isBullish
          ? "bg-emerald-500/20 text-emerald-400"
          : "bg-red-500/20 text-red-400"
      }`}
    >
      {isBullish ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
      {isBullish ? "看多" : "看空"}
    </span>
  )
}

function ActionBadge({ action }: { action: string }) {
  const isBuy = action === "buy"
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
        isBuy
          ? "bg-emerald-500/20 text-emerald-400"
          : "bg-red-500/20 text-red-400"
      }`}
    >
      {isBuy ? "买入" : "卖出"}
    </span>
  )
}

function ThesesTable({ theses }: { theses: InvestmentThesis[] }) {
  if (theses.length === 0) {
    return <div className="text-sm text-gray-500 py-6 text-center">暂无活跃投资主题</div>
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-gray-400 border-b border-gray-700/50">
            <th className="text-left py-2 px-3 font-medium">代码</th>
            <th className="text-left py-2 px-3 font-medium">名称</th>
            <th className="text-left py-2 px-3 font-medium">方向</th>
            <th className="text-left py-2 px-3 font-medium min-w-[120px]">置信度</th>
            <th className="text-left py-2 px-3 font-medium">主题摘要</th>
            <th className="text-left py-2 px-3 font-medium">更新时间</th>
          </tr>
        </thead>
        <tbody>
          {theses.map((t) => (
            <tr key={`${t.symbol}-${t.updated_at}`} className="border-b border-gray-800/50 hover:bg-gray-800/40">
              <td className="py-2.5 px-3 font-mono text-gray-200">{t.symbol}</td>
              <td className="py-2.5 px-3 text-gray-300">{t.name}</td>
              <td className="py-2.5 px-3"><DirectionBadge direction={t.direction} /></td>
              <td className="py-2.5 px-3"><ConvictionBar value={t.conviction} /></td>
              <td className="py-2.5 px-3 text-gray-400 max-w-xs truncate" title={t.thesis_text}>{t.thesis_text}</td>
              <td className="py-2.5 px-3 text-gray-500 text-xs whitespace-nowrap">{fmtDate(t.updated_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function DecisionsTable({ decisions }: { decisions: DecisionOutcome[] }) {
  if (decisions.length === 0) {
    return <div className="text-sm text-gray-500 py-6 text-center">暂无决策记录</div>
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-gray-400 border-b border-gray-700/50">
            <th className="text-left py-2 px-3 font-medium">代码</th>
            <th className="text-left py-2 px-3 font-medium">操作</th>
            <th className="text-right py-2 px-3 font-medium">决策价格</th>
            <th className="text-right py-2 px-3 font-medium">T+1</th>
            <th className="text-right py-2 px-3 font-medium">T+3</th>
            <th className="text-right py-2 px-3 font-medium">T+5</th>
            <th className="text-left py-2 px-3 font-medium">决策时间</th>
          </tr>
        </thead>
        <tbody>
          {decisions.map((d) => (
            <tr key={d.decision_id} className="border-b border-gray-800/50 hover:bg-gray-800/40">
              <td className="py-2.5 px-3 font-mono text-gray-200">{d.symbol}</td>
              <td className="py-2.5 px-3"><ActionBadge action={d.action} /></td>
              <td className="py-2.5 px-3 text-right text-gray-300">{d.decided_price.toFixed(2)}</td>
              <td className={`py-2.5 px-3 text-right font-mono ${pctColor(d.t1_return_pct)}`}>{fmtPct(d.t1_return_pct)}</td>
              <td className={`py-2.5 px-3 text-right font-mono ${pctColor(d.t3_return_pct)}`}>{fmtPct(d.t3_return_pct)}</td>
              <td className={`py-2.5 px-3 text-right font-mono ${pctColor(d.t5_return_pct)}`}>{fmtPct(d.t5_return_pct)}</td>
              <td className="py-2.5 px-3 text-gray-500 text-xs whitespace-nowrap">{fmtDate(d.decided_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function CalibrationCard({ report }: { report: CalibrationReport }) {
  if (report.status === "no_data") {
    return (
      <div className="text-sm text-gray-500 py-4 text-center">
        暂无校准数据 — 需要至少 {5} 条已评估决策
      </div>
    )
  }

  const actions = Object.entries(report.by_action)

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="rounded-lg bg-gray-700/40 p-3">
          <div className="text-xs text-gray-400">校准状态</div>
          <div className={`text-sm font-medium mt-1 ${report.calibration_active ? "text-emerald-400" : "text-amber-400"}`}>
            {report.calibration_active ? "已激活" : "样本不足"}
          </div>
        </div>
        <div className="rounded-lg bg-gray-700/40 p-3">
          <div className="text-xs text-gray-400">总体准确率</div>
          <div className="text-sm font-medium mt-1 text-gray-200">
            {report.overall_accuracy != null ? `${(report.overall_accuracy * 100).toFixed(1)}%` : "--"}
          </div>
        </div>
        <div className="rounded-lg bg-gray-700/40 p-3">
          <div className="text-xs text-gray-400">已评估</div>
          <div className="text-sm font-medium mt-1 text-gray-200">
            {report.evaluated_decisions} / {report.total_decisions}
          </div>
        </div>
        <div className="rounded-lg bg-gray-700/40 p-3">
          <div className="text-xs text-gray-400">回溯窗口</div>
          <div className="text-sm font-medium mt-1 text-gray-200">{report.lookback_days}天</div>
        </div>
      </div>

      {actions.length > 0 && (
        <div>
          <div className="text-xs text-gray-400 mb-2">按操作类型</div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {actions.map(([action, stats]) => (
              <div key={action} className="rounded-lg bg-gray-700/30 p-2.5">
                <div className="text-xs font-medium text-gray-300 capitalize">{action === "buy" ? "买入" : action === "sell" ? "卖出" : action}</div>
                <div className="text-lg font-bold text-gray-100 mt-0.5">
                  {stats.accuracy != null ? `${(stats.accuracy * 100).toFixed(0)}%` : "--"}
                </div>
                <div className="text-xs text-gray-500">{stats.total} 笔</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function AgentDashboard() {
  const queryClient = useQueryClient()
  const [cycleResult, setCycleResult] = useState<CycleResult | null>(null)

  const { data: status, isLoading, error } = useQuery<AgentStatus>({
    queryKey: ["agent-status"],
    queryFn: fetchAgentStatus,
    refetchInterval: 60_000,
  })

  const { data: theses } = useQuery<InvestmentThesis[]>({
    queryKey: ["agent-theses"],
    queryFn: () => fetchAgentTheses(false),
    refetchInterval: 60_000,
  })

  const { data: decisions } = useQuery<DecisionOutcome[]>({
    queryKey: ["agent-decisions"],
    queryFn: () => fetchAgentDecisions(20),
    refetchInterval: 60_000,
  })

  const { data: calibration } = useQuery<CalibrationReport>({
    queryKey: ["agent-calibration"],
    queryFn: fetchCalibrationReport,
    refetchInterval: 120_000,
  })

  const cycleMutation = useMutation({
    mutationFn: triggerAgentCycle,
    onSuccess: (result) => {
      setCycleResult(result)
      queryClient.invalidateQueries({ queryKey: ["agent-status"] })
      queryClient.invalidateQueries({ queryKey: ["agent-theses"] })
      queryClient.invalidateQueries({ queryKey: ["agent-decisions"] })
    },
  })

  const accuracy = status?.accuracy

  return (
    <div className="min-h-screen bg-gray-900 text-gray-100 p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Brain className="h-6 w-6 text-violet-400" />
          <h1 className="text-2xl font-bold">Agent Brain</h1>
          {status && (
            <span className="flex items-center gap-1.5 text-xs text-emerald-400">
              <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
              运行中
            </span>
          )}
        </div>
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="flex items-center gap-2 text-sm text-gray-400 py-8 justify-center">
          <Loader2 className="h-4 w-4 animate-spin" />
          加载代理数据...
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-500/50 bg-red-500/10 p-4 text-sm text-red-400">
          加载失败: {(error as Error).message}
        </div>
      )}

      {/* Stats Bar */}
      {status && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            icon={<Target className="h-4 w-4 text-violet-400" />}
            label="活跃主题"
            value={status.active_theses}
            sub="当前跟踪的投资主题"
          />
          <StatCard
            icon={<ListChecks className="h-4 w-4 text-blue-400" />}
            label="总决策数"
            value={accuracy?.total_decisions ?? 0}
            sub={`盈利 ${accuracy?.profitable_decisions ?? 0} 笔`}
          />
          <StatCard
            icon={<Activity className="h-4 w-4 text-emerald-400" />}
            label="方向准确率"
            value={accuracy ? `${(accuracy.direction_accuracy * 100).toFixed(1)}%` : "--"}
            sub="近30天决策方向"
          />
          <StatCard
            icon={<BarChart3 className="h-4 w-4 text-amber-400" />}
            label="平均 T+3 收益"
            value={accuracy ? fmtPct(accuracy.avg_t3_return) : "--"}
            sub={`T+1: ${accuracy ? fmtPct(accuracy.avg_t1_return) : "--"}`}
          />
        </div>
      )}

      {/* Active Theses */}
      <div className="rounded-xl bg-gray-800/40 border border-gray-700/50">
        <div className="px-5 py-4 border-b border-gray-700/50">
          <h2 className="text-lg font-semibold text-gray-200">活跃投资主题</h2>
        </div>
        <div className="p-2">
          <ThesesTable theses={theses ?? status?.theses ?? []} />
        </div>
      </div>

      {/* Recent Decisions */}
      <div className="rounded-xl bg-gray-800/40 border border-gray-700/50">
        <div className="px-5 py-4 border-b border-gray-700/50">
          <h2 className="text-lg font-semibold text-gray-200">近期决策记录</h2>
        </div>
        <div className="p-2">
          <DecisionsTable decisions={decisions ?? status?.recent_decisions ?? []} />
        </div>
      </div>

      {/* Confidence Calibration (Phase 5) */}
      {calibration && (
        <div className="rounded-xl bg-gray-800/40 border border-gray-700/50">
          <div className="px-5 py-4 border-b border-gray-700/50 flex items-center gap-2">
            <Gauge className="h-4 w-4 text-violet-400" />
            <h2 className="text-lg font-semibold text-gray-200">置信度校准</h2>
            {calibration.calibration_active && (
              <Shield className="h-3.5 w-3.5 text-emerald-400 ml-1" />
            )}
          </div>
          <div className="p-4">
            <CalibrationCard report={calibration} />
          </div>
        </div>
      )}

      {/* Manual Cycle Trigger */}
      <div className="rounded-xl bg-gray-800/40 border border-gray-700/50 p-5">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-200">手动触发 OODA 循环</h2>
            <p className="text-sm text-gray-500 mt-1">执行一次完整的观察-判断-决策-行动循环</p>
          </div>
          <button
            onClick={() => cycleMutation.mutate()}
            disabled={cycleMutation.isPending}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-violet-600 hover:bg-violet-500 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium transition-colors"
          >
            {cycleMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Play className="h-4 w-4" />
            )}
            触发 OODA 循环
          </button>
        </div>

        {/* Cycle error */}
        {cycleMutation.isError && (
          <div className="mt-4 rounded-lg border border-red-500/50 bg-red-500/10 p-3 text-sm text-red-400">
            循环执行失败: {(cycleMutation.error as Error).message}
          </div>
        )}

        {/* Cycle result */}
        {cycleResult && (
          <div className="mt-4 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-4 text-sm">
            <div className="text-emerald-400 font-medium mb-2">循环完成</div>
            <div className="grid grid-cols-2 gap-2 text-gray-300">
              <div>循环 ID: <span className="font-mono text-gray-400">{cycleResult.cycle_id}</span></div>
              <div>处理信号数: <span className="font-mono text-gray-400">{cycleResult.signals_processed}</span></div>
              <div>生成提案数: <span className="font-mono text-gray-400">{cycleResult.proposals_generated.length}</span></div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
