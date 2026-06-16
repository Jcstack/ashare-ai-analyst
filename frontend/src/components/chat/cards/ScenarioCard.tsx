/** Scenario analysis rich card — displays bullish/base/bearish outcomes
 *  with probability bars, risk badges, and key drivers. */

import { useState } from "react"
import { TrendingUp, TrendingDown, Minus, ChevronDown } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { formatPrice } from "@/lib/formatters"

interface ScenarioData {
  name: string
  probability: number
  description: string
  target_price?: number
  risk_level?: "low" | "medium" | "high"
  key_drivers?: string[]
}

interface ScenarioCardProps {
  props: Record<string, unknown>
}

const RISK_CONFIG: Record<string, { label: string; color: string; barColor: string }> = {
  low: { label: "低风险", color: "text-market-up", barColor: "bg-market-up" },
  medium: { label: "中风险", color: "text-warning", barColor: "bg-warning" },
  high: { label: "高风险", color: "text-market-down", barColor: "bg-market-down" },
}

function scenarioIcon(name: string) {
  const n = name.toLowerCase()
  if (n.includes("bull") || n.includes("乐观") || n.includes("看涨")) return TrendingUp
  if (n.includes("bear") || n.includes("悲观") || n.includes("看跌")) return TrendingDown
  return Minus
}

export function ScenarioCard({ props }: ScenarioCardProps) {
  const title = typeof props.title === "string" ? props.title : "情景分析"
  const symbol = typeof props.symbol === "string" ? props.symbol : undefined
  const scenarios = Array.isArray(props.scenarios)
    ? (props.scenarios as ScenarioData[])
    : []

  if (scenarios.length === 0) return null

  return (
    <div className="rounded-md border bg-bg-surface p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center gap-2">
        <span className="font-semibold text-sm">{title}</span>
        {symbol && (
          <span className="text-xs text-muted-foreground">{symbol}</span>
        )}
        <Badge variant="secondary" className="ml-auto text-[10px]">
          {scenarios.length} 种情景
        </Badge>
      </div>

      {/* Scenario rows */}
      <div className="space-y-0">
        {scenarios.map((s, i) => (
          <ScenarioRow key={i} scenario={s} />
        ))}
      </div>
    </div>
  )
}

function ScenarioRow({ scenario }: { scenario: ScenarioData }) {
  const [expanded, setExpanded] = useState(false)
  const pct = Math.round(scenario.probability * 100)
  const risk = RISK_CONFIG[scenario.risk_level ?? "medium"] ?? RISK_CONFIG.medium
  const Icon = scenarioIcon(scenario.name)
  const hasDetails = !!scenario.description || (scenario.key_drivers && scenario.key_drivers.length > 0)

  return (
    <div className="py-2 border-b border-border-subtle last:border-b-0">
      {/* Main row */}
      <div
        className={cn(
          "flex items-center gap-2 text-xs",
          hasDetails && "cursor-pointer",
        )}
        onClick={() => hasDetails && setExpanded(!expanded)}
      >
        <Icon className={cn("h-3.5 w-3.5 shrink-0", risk.color)} />
        <span className="w-14 font-medium shrink-0 truncate">{scenario.name}</span>
        <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
          <div
            className={cn("h-full rounded-full transition-all", risk.barColor)}
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="w-8 text-right font-numeric font-medium">{pct}%</span>
        {scenario.target_price != null && (
          <span className="text-muted-foreground font-numeric shrink-0">
            目标 {formatPrice(scenario.target_price)}
          </span>
        )}
        <Badge variant="secondary" className={cn("text-[10px] px-1.5 py-0 shrink-0", risk.color)}>
          {risk.label}
        </Badge>
        {hasDetails && (
          <ChevronDown
            className={cn(
              "h-3 w-3 text-text-disabled transition-transform shrink-0",
              expanded && "rotate-180",
            )}
          />
        )}
      </div>

      {/* Expanded details */}
      {expanded && (
        <div className="mt-1.5 ml-6 space-y-1">
          {scenario.description && (
            <p className="text-xs text-text-secondary leading-relaxed">
              {scenario.description}
            </p>
          )}
          {scenario.key_drivers && scenario.key_drivers.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {scenario.key_drivers.map((d, i) => (
                <Badge key={i} variant="secondary" className="text-[10px]">
                  {d}
                </Badge>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
