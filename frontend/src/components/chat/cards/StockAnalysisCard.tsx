/** Stock analysis rich card — displays structured analysis result.
 *  Also used for market_overview and portfolio_summary card types. */

import { useState } from "react"
import {
  TrendingUp, TrendingDown, Minus, AlertTriangle, ChevronDown,
  AlertCircle, Eye, Database,
} from "lucide-react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

interface StockAnalysisCardProps {
  props: Record<string, unknown>
}

interface DimensionData {
  key: string
  label: string
  signal: string
  score: number
  reasoning: string
}

interface ScenarioData {
  name: string
  probability: number
  description: string
  target_price?: number
  risk_level?: string
  key_drivers?: string[]
}

const SIGNAL_CONFIG: Record<
  string,
  { label: string; icon: React.ElementType; variant: "up" | "down" | "secondary" }
> = {
  bullish: { label: "看多", icon: TrendingUp, variant: "up" },
  bearish: { label: "看空", icon: TrendingDown, variant: "down" },
  neutral: { label: "中性", icon: Minus, variant: "secondary" },
}

export function StockAnalysisCard({ props }: StockAnalysisCardProps) {
  const title = typeof props.title === "string" ? props.title : undefined
  const symbol = typeof props.symbol === "string" ? props.symbol : undefined
  const signal = typeof props.signal === "string" ? props.signal : "neutral"
  const confidence = typeof props.confidence === "number" ? props.confidence : 0
  const summary = typeof props.summary === "string" ? props.summary : ""
  const dimensions = Array.isArray(props.dimensions)
    ? (props.dimensions as DimensionData[])
    : []
  const riskWarnings = Array.isArray(props.risk_warnings)
    ? (props.risk_warnings as string[])
    : []

  // Five-element output fields
  const keyAssumptions = Array.isArray(props.key_assumptions)
    ? (props.key_assumptions as string[])
    : []
  const failureModes = Array.isArray(props.failure_modes)
    ? (props.failure_modes as string[])
    : []
  const dataGaps = Array.isArray(props.data_gaps)
    ? (props.data_gaps as string[])
    : []
  const scenarios = Array.isArray(props.scenarios)
    ? (props.scenarios as ScenarioData[])
    : []

  const config = SIGNAL_CONFIG[signal] ?? SIGNAL_CONFIG.neutral
  const Icon = config.icon

  return (
    <div className="rounded-md border bg-bg-surface p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center gap-2 flex-wrap">
        {title && (
          <span className="font-semibold text-sm">{title}</span>
        )}
        {symbol && !title ? (
          <span className="font-semibold text-sm">{symbol}</span>
        ) : symbol && title ? (
          <span className="text-xs text-muted-foreground">{symbol}</span>
        ) : null}
        <Badge variant={config.variant}>
          <Icon className="mr-1 h-3 w-3" />
          {config.label}
        </Badge>
        {confidence > 0 ? (
          <div className="flex items-center gap-1.5 ml-auto">
            <span className="text-xs text-muted-foreground">置信度</span>
            <div className="w-20 h-1.5 bg-muted rounded-full overflow-hidden">
              <div
                className={cn(
                  "h-full rounded-full",
                  confidence >= 0.7
                    ? "bg-market-up"
                    : confidence >= 0.4
                      ? "bg-warning"
                      : "bg-muted-foreground",
                )}
                style={{ width: `${confidence * 100}%` }}
              />
            </div>
            <span className="text-xs font-numeric">
              {(confidence * 100).toFixed(0)}%
            </span>
          </div>
        ) : null}
      </div>

      {/* Summary — markdown rendered */}
      {summary ? (
        <div className="prose prose-sm dark:prose-invert max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{summary}</ReactMarkdown>
        </div>
      ) : null}

      {/* Dimensions with expandable reasoning */}
      {dimensions.length > 0 ? (
        <div className="space-y-0">
          {dimensions.map((dim) => (
            <DimensionRow key={dim.key ?? dim.label} dim={dim} />
          ))}
        </div>
      ) : null}

      {/* Risk warning */}
      {riskWarnings.length > 0 ? (
        <div className="flex items-start gap-1.5 text-xs text-warning border-l-2 border-warning pl-2">
          <AlertTriangle className="h-3 w-3 mt-0.5 shrink-0" />
          <span>{riskWarnings.join("; ")}</span>
        </div>
      ) : null}

      {/* Key assumptions (collapsible) */}
      {keyAssumptions.length > 0 ? (
        <CollapsibleSection
          icon={Eye}
          title="关键假设"
          count={keyAssumptions.length}
        >
          <ul className="ml-5 list-disc text-xs text-text-secondary space-y-0.5">
            {keyAssumptions.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </CollapsibleSection>
      ) : null}

      {/* Failure modes (collapsible) */}
      {failureModes.length > 0 ? (
        <CollapsibleSection
          icon={AlertCircle}
          title="失效场景"
          count={failureModes.length}
        >
          <ul className="ml-5 list-disc text-xs text-text-secondary space-y-0.5">
            {failureModes.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </CollapsibleSection>
      ) : null}

      {/* Data gaps (warning chips) */}
      {dataGaps.length > 0 ? (
        <div className="flex items-start gap-1.5 flex-wrap">
          <Database className="h-3 w-3 text-muted-foreground mt-0.5 shrink-0" />
          {dataGaps.map((gap, i) => (
            <Badge key={i} variant="secondary" className="text-[10px]">
              {gap}
            </Badge>
          ))}
        </div>
      ) : null}

      {/* Scenarios */}
      {scenarios.length > 0 ? (
        <div className="border-t border-border-subtle pt-2.5 space-y-1.5">
          <span className="text-[10px] text-text-tertiary uppercase tracking-wider">
            情景分析
          </span>
          {scenarios.map((s, i) => (
            <ScenarioRow key={i} scenario={s} />
          ))}
        </div>
      ) : null}
    </div>
  )
}

/** Collapsible section for assumptions / failure modes */
function CollapsibleSection({
  icon: Icon,
  title,
  count,
  children,
}: {
  icon: React.ElementType
  title: string
  count: number
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className="border-t border-border-subtle pt-2">
      <button
        className="flex items-center gap-1.5 text-xs text-text-secondary w-full"
        onClick={() => setOpen(!open)}
      >
        <Icon className="h-3 w-3 shrink-0" />
        <span>{title}</span>
        <Badge variant="secondary" className="text-[10px] px-1.5 py-0 ml-1">
          {count}
        </Badge>
        <ChevronDown
          className={cn(
            "h-3 w-3 ml-auto text-text-disabled transition-transform",
            open && "rotate-180",
          )}
        />
      </button>
      {open && <div className="mt-1.5">{children}</div>}
    </div>
  )
}

/** Scenario row — probability bar + description */
function ScenarioRow({ scenario }: { scenario: ScenarioData }) {
  const pct = Math.round(scenario.probability * 100)
  const riskColor =
    scenario.risk_level === "high"
      ? "bg-market-down"
      : scenario.risk_level === "low"
        ? "bg-market-up"
        : "bg-warning"

  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-12 text-muted-foreground shrink-0 truncate">
        {scenario.name}
      </span>
      <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
        <div
          className={cn("h-full rounded-full", riskColor)}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-8 text-right font-numeric text-muted-foreground">
        {pct}%
      </span>
    </div>
  )
}

/** Dimension row with expandable reasoning */
function DimensionRow({ dim }: { dim: DimensionData }) {
  const [expanded, setExpanded] = useState(false)
  const dimConfig = SIGNAL_CONFIG[dim.signal] ?? SIGNAL_CONFIG.neutral
  const pct = Math.round(dim.score * 100)
  const hasReasoning = !!dim.reasoning

  return (
    <div className="py-1.5 border-b border-border-subtle last:border-b-0">
      <div
        className={cn(
          "flex items-center gap-2 text-xs",
          hasReasoning && "cursor-pointer",
        )}
        onClick={() => hasReasoning && setExpanded(!expanded)}
      >
        <span className="w-16 text-muted-foreground shrink-0">
          {dim.label}
        </span>
        <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
          <div
            className={cn(
              "h-full rounded-full",
              dim.signal === "bullish"
                ? "bg-market-up"
                : dim.signal === "bearish"
                  ? "bg-market-down"
                  : "bg-muted-foreground",
            )}
            style={{ width: `${pct}%` }}
          />
        </div>
        <Badge
          variant={dimConfig.variant}
          className="text-[10px] px-1.5 py-0"
        >
          {dimConfig.label}
        </Badge>
        {hasReasoning && (
          <ChevronDown
            className={cn(
              "h-3 w-3 text-text-disabled transition-transform",
              expanded && "rotate-180",
            )}
          />
        )}
      </div>
      {expanded && dim.reasoning && (
        <p className="mt-1 ml-[72px] text-xs text-text-secondary leading-relaxed">
          {dim.reasoning}
        </p>
      )}
    </div>
  )
}
