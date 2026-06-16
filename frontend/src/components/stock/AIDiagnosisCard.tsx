import { useState } from "react"
import { formatTime } from "@/lib/formatters"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import {
  BrainCircuit,
  AlertTriangle,
  Target,
  ShieldAlert,
  Loader2,
  ChevronDown,
  ChevronUp,
  TrendingUp,
  TrendingDown,
  Minus,
  RefreshCw,
} from "lucide-react"
import { useStockAdvice } from "@/hooks/useAdvisor"
import { useComprehensiveAnalysis } from "@/hooks/useFundFlow"
import { useLatestSignals } from "@/hooks/useBacktest"

interface AIDiagnosisCardProps {
  symbol: string
}

const ACTION_COLORS: Record<string, { text: string; bg: string; border: string }> = {
  buy:    { text: "text-market-up",   bg: "bg-market-up/10",   border: "border-market-up/30" },
  add:    { text: "text-market-up",   bg: "bg-market-up/10",   border: "border-market-up/30" },
  hold:   { text: "text-muted-foreground", bg: "bg-muted/50",       border: "border-muted" },
  reduce: { text: "text-market-down", bg: "bg-market-down/10", border: "border-market-down/30" },
  sell:   { text: "text-market-down", bg: "bg-market-down/10", border: "border-market-down/30" },
  watch:  { text: "text-info",    bg: "bg-info/10",    border: "border-info/30" },
}

const RISK_BADGE: Record<string, { label: string; variant: "default" | "secondary" | "destructive" }> = {
  low:    { label: "低风险", variant: "secondary" },
  medium: { label: "中风险", variant: "default" },
  high:   { label: "高风险", variant: "destructive" },
}

const SIGNAL_ICON = {
  buy: TrendingUp,
  sell: TrendingDown,
  hold: Minus,
}

export function AIDiagnosisCard({ symbol }: AIDiagnosisCardProps) {
  const [enabled, setEnabled] = useState(false)
  const { data: advice, isLoading: adviceLoading, error: adviceError } = useStockAdvice(symbol, enabled)
  const { data: comprehensive, isLoading: compLoading } = useComprehensiveAnalysis(symbol)
  const { data: signals } = useLatestSignals(symbol)
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set())

  const toggleSection = (key: string) => {
    setExpandedSections((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  // Quick summary from comprehensive analysis (auto-loads)
  const quickSummary = comprehensive?.summary

  // Not yet triggered — show invitation card
  if (!enabled) {
    return (
      <Card className="border-l-2 border-l-[var(--accent-primary)]">
        <CardContent className="p-5 space-y-4">
          <div className="flex items-center gap-2">
            <BrainCircuit className="h-5 w-5 text-accent-primary" />
            <span className="text-sm font-semibold">AI 综合诊断</span>
          </div>

          {/* Show quick summary if available */}
          {compLoading && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <RefreshCw className="h-3.5 w-3.5 animate-spin" />
              正在加载速览...
            </div>
          )}
          {quickSummary && (
            <p className="text-sm text-foreground leading-relaxed">{quickSummary}</p>
          )}

          <div className="text-center pt-2">
            <p className="text-xs text-muted-foreground mb-3">
              综合技术面、资金面、概念板块、舆情等多维数据，AI 一键生成操作建议
            </p>
            <Button size="sm" onClick={() => setEnabled(true)}>
              <BrainCircuit className="h-3.5 w-3.5 mr-1.5" />
              一键分析
            </Button>
          </div>
        </CardContent>
      </Card>
    )
  }

  // Loading state
  if (adviceLoading) {
    return (
      <Card className="border-l-2 border-l-[var(--accent-primary)]">
        <CardContent className="p-5 space-y-4">
          <div className="flex items-center gap-2">
            <BrainCircuit className="h-5 w-5 text-accent-primary" />
            <span className="text-sm font-semibold">AI 综合诊断</span>
          </div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            正在综合分析技术面、资金面、概念板块...
          </div>
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-16 w-full" />
        </CardContent>
      </Card>
    )
  }

  // Error state
  if (adviceError || !advice || advice.status === "error") {
    return (
      <Card className="border-l-2 border-l-[var(--accent-primary)]">
        <CardContent className="p-5 space-y-3">
          <div className="flex items-center gap-2">
            <BrainCircuit className="h-5 w-5 text-accent-primary" />
            <span className="text-sm font-semibold">AI 综合诊断</span>
          </div>
          {quickSummary && (
            <p className="text-sm text-foreground leading-relaxed">{quickSummary}</p>
          )}
          <div className="text-center py-2 space-y-2">
            <p className="text-xs text-muted-foreground">
              {advice?.message || "分析暂时不可用，请稍后重试"}
            </p>
            <Button size="sm" variant="outline" onClick={() => setEnabled(false)}>
              重试
            </Button>
          </div>
        </CardContent>
      </Card>
    )
  }

  const actionStyle = ACTION_COLORS[advice.action] ?? ACTION_COLORS.watch
  const riskBadge = RISK_BADGE[advice.risk_level] ?? RISK_BADGE.medium
  const pct = Math.round(advice.confidence * 100)

  return (
    <Card className="border-l-2 border-l-[var(--accent-primary)]">
      <CardContent className="p-5 space-y-4">
        {/* Header: title + timestamp */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <BrainCircuit className="h-5 w-5 text-accent-primary" />
            <span className="text-sm font-semibold">AI 综合诊断</span>
          </div>
          <span className="text-[10px] text-muted-foreground/60">{formatTime(advice.generated_at)}</span>
        </div>

        {/* Signal badge + confidence bar + risk level */}
        <div className="flex items-center gap-3">
          <div className={`rounded-lg px-4 py-2 font-bold text-base ${actionStyle.bg} ${actionStyle.text} border ${actionStyle.border}`}>
            {advice.action_label}
          </div>
          <div className="flex items-center gap-2 flex-1">
            <span className="text-xs text-muted-foreground shrink-0">置信度</span>
            <div className="flex-1 h-2.5 bg-muted rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{
                  width: `${pct}%`,
                  backgroundColor: pct > 70 ? "var(--color-market-up)" : pct > 40 ? "#f59e0b" : "var(--color-market-flat)",
                }}
              />
            </div>
            <span className="text-sm font-mono font-semibold w-10 text-right">{pct}%</span>
          </div>
          <Badge variant={riskBadge.variant} className="text-xs">
            {riskBadge.label}
          </Badge>
        </div>

        {/* One-line summary (from comprehensive analysis) */}
        {quickSummary && (
          <p className="text-sm text-foreground leading-relaxed font-medium">{quickSummary}</p>
        )}

        {/* Collapsible: AI Reasoning (技术面 + 资金面 etc) */}
        {advice.ai_reasoning.length > 0 && (
          <CollapsibleSection
            title="AI 研判分析"
            isOpen={expandedSections.has("reasoning")}
            onToggle={() => toggleSection("reasoning")}
          >
            <ul className="space-y-1.5">
              {advice.ai_reasoning.map((point, i) => (
                <li key={i} className="text-xs flex items-start gap-1.5">
                  <span className="text-accent-primary mt-0.5 shrink-0">•</span>
                  <span>{point}</span>
                </li>
              ))}
            </ul>
          </CollapsibleSection>
        )}

        {/* Collapsible: Quant Signals */}
        {advice.quant_signals && Object.keys(advice.quant_signals).length > 0 && (
          <CollapsibleSection
            title="量化信号"
            isOpen={expandedSections.has("quant")}
            onToggle={() => toggleSection("quant")}
          >
            <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
              {advice.quant_signals.technical_score != null && (
                <QuantRow label="技术分" value={advice.quant_signals.technical_score} />
              )}
              {advice.quant_signals.momentum_score != null && (
                <QuantRow label="动量分" value={advice.quant_signals.momentum_score} />
              )}
              {advice.quant_signals.bayesian_probability != null && (
                <QuantRow label="贝叶斯概率" value={advice.quant_signals.bayesian_probability} />
              )}
              {advice.quant_signals.strategy_consensus && (
                <div className="flex justify-between text-xs">
                  <span className="text-muted-foreground">策略共识</span>
                  <span className="font-medium">{advice.quant_signals.strategy_consensus}</span>
                </div>
              )}
            </div>
          </CollapsibleSection>
        )}

        {/* Collapsible: Strategy Signals */}
        {signals && signals.length > 0 && (
          <CollapsibleSection
            title="策略信号"
            isOpen={expandedSections.has("strategy")}
            onToggle={() => toggleSection("strategy")}
          >
            <div className="space-y-1.5">
              {signals.map((sig) => {
                const Icon = SIGNAL_ICON[sig.signal] ?? Minus
                const signalColor = sig.signal === "buy" ? "#EF5350" : sig.signal === "sell" ? "#26A69A" : "#94a3b8"
                return (
                  <div key={sig.strategy_key} className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-1.5">
                      <Icon className="h-3 w-3" style={{ color: signalColor }} />
                      <span>{sig.strategy_name}</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <div className="w-10 h-1 bg-muted rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full"
                          style={{ width: `${sig.strength * 100}%`, backgroundColor: signalColor }}
                        />
                      </div>
                      <span style={{ color: signalColor }}>
                        {sig.signal === "buy" ? "买入" : sig.signal === "sell" ? "卖出" : "持有"}
                      </span>
                    </div>
                  </div>
                )
              })}
            </div>
          </CollapsibleSection>
        )}

        {/* Target price + stop loss */}
        {(advice.target_price || advice.stop_loss) && (
          <div className="flex gap-4 text-xs border-t pt-3">
            {advice.target_price && (
              <div className="flex items-center gap-1.5 text-muted-foreground">
                <Target className="h-3.5 w-3.5" />
                <span>目标价: </span>
                <span className="font-medium text-foreground">
                  {advice.target_price.low.toFixed(2)} ~ {advice.target_price.high.toFixed(2)}
                </span>
              </div>
            )}
            {advice.stop_loss && (
              <div className="flex items-center gap-1.5 text-muted-foreground">
                <ShieldAlert className="h-3.5 w-3.5" />
                <span>止损位: </span>
                <span className="font-medium text-foreground">{advice.stop_loss.toFixed(2)}</span>
              </div>
            )}
          </div>
        )}

        {/* Risk warnings */}
        {advice.risk_warnings.length > 0 && (
          <div className="rounded-lg border border-warning/20 bg-warning/5 p-3 space-y-1">
            <div className="flex items-center gap-1 text-xs font-medium text-warning">
              <AlertTriangle className="h-3.5 w-3.5" />
              风险提示
            </div>
            {advice.risk_warnings.map((w, i) => (
              <p key={i} className="text-xs text-warning/80">• {w}</p>
            ))}
          </div>
        )}

        {/* Disclaimer */}
        <p className="text-[10px] text-muted-foreground/60 border-t pt-2">
          AI 分析仅供参考，不构成任何投资建议。股市有风险，投资需谨慎。
        </p>
      </CardContent>
    </Card>
  )
}

/** Collapsible section with toggle */
function CollapsibleSection({
  title,
  isOpen,
  onToggle,
  children,
}: {
  title: string
  isOpen: boolean
  onToggle: () => void
  children: React.ReactNode
}) {
  return (
    <div className="rounded-lg border p-3 space-y-2">
      <button
        onClick={onToggle}
        className="flex items-center justify-between w-full text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
      >
        <span>{title}</span>
        {isOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
      </button>
      {isOpen && <div className="pt-1">{children}</div>}
    </div>
  )
}

function QuantRow({ label, value }: { label: string; value: number }) {
  const pct = Math.round(value * 100)
  return (
    <div className="flex justify-between items-center text-xs">
      <span className="text-muted-foreground">{label}</span>
      <div className="flex items-center gap-1.5">
        <div className="w-12 h-1 bg-muted rounded-full overflow-hidden">
          <div
            className="h-full rounded-full"
            style={{
              width: `${pct}%`,
              backgroundColor: pct > 60 ? "var(--color-market-up)" : pct > 40 ? "#f59e0b" : "var(--color-market-flat)",
            }}
          />
        </div>
        <span className="font-mono w-6 text-right">{pct}%</span>
      </div>
    </div>
  )
}
