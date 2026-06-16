import { useState } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ChevronDown, ChevronUp, Sparkles, AlertTriangle, RefreshCw } from "lucide-react"
import { HealthScoreGauge } from "./HealthScoreGauge"
import { POSITION_ACTION_LABELS, POSITION_ACTION_COLORS, RISK_COLORS } from "@/lib/constants"
import type { PortfolioDiagnosis } from "@/types/portfolio"

interface Props {
  diagnosis: PortfolioDiagnosis | null
  isLoading: boolean
  error: Error | null
  onRetry?: () => void
}

export function DiagnosisPanel({ diagnosis, isLoading, error, onRetry }: Props) {
  const [showReasoning, setShowReasoning] = useState(false)

  if (error) {
    return (
      <Card className="border-destructive/30">
        <CardContent className="p-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-destructive">AI 诊断失败: {error.message}</p>
            {onRetry && (
              <Button variant="outline" size="sm" onClick={onRetry} className="ml-3 shrink-0">
                <RefreshCw className="h-3.5 w-3.5 mr-1" /> 重试
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    )
  }

  if (isLoading) {
    return (
      <Card className="border-l-2 border-l-[var(--accent-primary)]">
        <CardContent className="p-6">
          <div className="flex items-center gap-3">
            <RefreshCw className="h-5 w-5 text-accent-primary animate-spin" />
            <div>
              <p className="text-sm font-medium">AI 正在诊断持仓...</p>
              <div className="flex items-center gap-2 mt-2">
                <span className="ai-dot" />
                <span className="ai-dot" />
                <span className="ai-dot" />
                <span className="text-xs text-muted-foreground ml-1">分析技术指标、评估风险集中度</span>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    )
  }

  if (!diagnosis) return null

  if (diagnosis.status !== "success") {
    return (
      <Card className="border-destructive/30">
        <CardContent className="p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-destructive" />
              <p className="text-sm text-destructive">
                {diagnosis.message || "AI 诊断未成功，请重试"}
              </p>
            </div>
            {onRetry && (
              <Button variant="outline" size="sm" onClick={onRetry} className="ml-3 shrink-0">
                <RefreshCw className="h-3.5 w-3.5 mr-1" /> 重试
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    )
  }

  const crLevel = diagnosis.concentration_risk?.level
  const crColor = crLevel ? RISK_COLORS[crLevel as keyof typeof RISK_COLORS] ?? RISK_COLORS.medium : undefined

  return (
    <Card className="border-l-2 border-l-[var(--accent-primary)] overflow-hidden">
      <CardContent className="p-5 space-y-5">
        {/* Header + Score */}
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 space-y-2">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-accent-primary" />
              <span className="text-title">AI 持仓诊断</span>
              {diagnosis.model_used && (
                <Badge variant="outline" className="text-[10px] border-accent-primary/30 text-accent-primary">
                  {diagnosis.model_used}
                </Badge>
              )}
            </div>
            <p className="text-sm text-muted-foreground leading-relaxed">
              {diagnosis.summary}
            </p>
          </div>
          <HealthScoreGauge score={diagnosis.health_score} label={diagnosis.health_label} />
        </div>

        {/* Concentration Risk */}
        {diagnosis.concentration_risk && (
          <div className="rounded-lg border p-3 space-y-1">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-3.5 w-3.5" style={{ color: crColor }} />
              <span className="text-xs font-medium">集中度风险</span>
              <Badge
                variant="outline"
                className="text-[10px]"
                style={{ borderColor: crColor, color: crColor }}
              >
                {crLevel === "low" ? "低" : crLevel === "medium" ? "中" : "高"}
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground">
              {diagnosis.concentration_risk.description}
            </p>
            {diagnosis.concentration_risk.top_holdings_pct != null && (
              <p className="text-xs text-muted-foreground">
                前3大持仓占比: {diagnosis.concentration_risk.top_holdings_pct.toFixed(1)}%
              </p>
            )}
          </div>
        )}

        {/* Position Advice */}
        {diagnosis.position_advice.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-medium text-muted-foreground">个股建议</p>
            <div className="space-y-1.5">
              {diagnosis.position_advice.map((advice) => (
                <div
                  key={advice.symbol}
                  className="flex items-center gap-2 rounded-md border px-3 py-2"
                >
                  <span className="text-sm font-medium flex-shrink-0">{advice.name}</span>
                  <Badge
                    variant="outline"
                    className="text-[10px] flex-shrink-0"
                    style={{
                      borderColor: POSITION_ACTION_COLORS[advice.action] ?? "var(--color-market-flat)",
                      color: POSITION_ACTION_COLORS[advice.action] ?? "var(--color-market-flat)",
                    }}
                  >
                    {POSITION_ACTION_LABELS[advice.action] ?? advice.action}
                  </Badge>
                  <span className="text-xs text-muted-foreground flex-1 truncate">
                    {advice.reason}
                  </span>
                  {advice.target_price != null && (
                    <span className="text-xs font-numeric text-muted-foreground flex-shrink-0">
                      目标 ¥{advice.target_price.toFixed(2)}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Rebalancing */}
        {diagnosis.rebalancing.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-xs font-medium text-muted-foreground">调仓建议</p>
            <ul className="text-xs text-muted-foreground space-y-1 border-l-2 border-accent-primary/30 pl-3">
              {diagnosis.rebalancing.map((item, i) => (
                <li key={i} className="leading-relaxed">{item}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Risk Warnings */}
        {diagnosis.risk_warnings.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-xs font-medium text-muted-foreground">风险提示</p>
            <div className="flex flex-wrap gap-1.5">
              {diagnosis.risk_warnings.map((warning, i) => (
                <Badge key={i} variant="outline" className="text-xs border-warning/40 text-warning">
                  <AlertTriangle className="h-3 w-3 mr-1" />
                  {warning}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {/* Reasoning chain (expandable) */}
        {diagnosis.reasoning.length > 0 && (
          <div>
            <button
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
              onClick={() => setShowReasoning(!showReasoning)}
            >
              {showReasoning ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
              {showReasoning ? "收起推理链" : "展开推理链"}
            </button>
            {showReasoning && (
              <ol className="mt-2 text-xs text-muted-foreground space-y-1 list-decimal list-inside">
                {diagnosis.reasoning.map((step, i) => (
                  <li key={i} className="leading-relaxed">{step}</li>
                ))}
              </ol>
            )}
          </div>
        )}

        {/* Footer */}
        {diagnosis.generated_at && (
          <p className="text-micro text-muted-foreground/50 text-right">
            生成于 {new Date(diagnosis.generated_at).toLocaleString("zh-CN")}
          </p>
        )}
      </CardContent>
    </Card>
  )
}
