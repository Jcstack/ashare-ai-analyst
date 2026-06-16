import { useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { ChevronDown } from "lucide-react"
import { cn } from "@/lib/utils"
import type { BayesianIndicatorItem } from "@/types/analysis"

/** A-share convention: red = up, green = down, gray = flat */
const PROB_COLORS = {
  up: "var(--color-market-up)",
  flat: "var(--color-market-flat)",
  down: "var(--color-market-down)",
} as const

const PROB_LABELS = {
  up: "涨",
  flat: "平",
  down: "跌",
} as const

interface IndicatorProbabilityBarProps {
  item: BayesianIndicatorItem
}

export function IndicatorProbabilityBar({ item }: IndicatorProbabilityBarProps) {
  const [open, setOpen] = useState(false)
  const { probabilities, indicator, current_value, bin_label, sample_count, analogy, interpretation, data_sufficient } = item

  // Determine dominant direction for the indicator label color
  const dominant = probabilities.up >= probabilities.down && probabilities.up >= probabilities.flat
    ? "up"
    : probabilities.down >= probabilities.up && probabilities.down >= probabilities.flat
      ? "down"
      : "flat"

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div className="rounded-lg border bg-card p-3 space-y-2">
        {/* Header row: indicator name, current value, bin label */}
        <CollapsibleTrigger className="w-full">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <span className="text-sm font-medium truncate">{indicator}</span>
              <span className="text-xs font-numeric text-muted-foreground shrink-0">
                {current_value.toFixed(2)}
              </span>
              <Badge variant="secondary" className="text-[10px] shrink-0">
                {bin_label}
              </Badge>
            </div>
            <ChevronDown
              className={cn(
                "h-4 w-4 text-muted-foreground shrink-0 transition-transform",
                open && "rotate-180",
              )}
            />
          </div>
        </CollapsibleTrigger>

        {/* Stacked probability bar */}
        <div className="space-y-1.5">
          <div className="flex h-5 w-full rounded-full overflow-hidden">
            {probabilities.up > 0 && (
              <div
                className="h-full flex items-center justify-center text-[10px] font-medium text-white transition-all"
                style={{
                  width: `${Math.max(probabilities.up * 100, 2)}%`,
                  backgroundColor: PROB_COLORS.up,
                }}
                title={`涨: ${(probabilities.up * 100).toFixed(1)}%`}
              >
                {probabilities.up >= 0.12 && `${(probabilities.up * 100).toFixed(0)}%`}
              </div>
            )}
            {probabilities.flat > 0 && (
              <div
                className="h-full flex items-center justify-center text-[10px] font-medium text-white transition-all"
                style={{
                  width: `${Math.max(probabilities.flat * 100, 2)}%`,
                  backgroundColor: PROB_COLORS.flat,
                }}
                title={`平: ${(probabilities.flat * 100).toFixed(1)}%`}
              >
                {probabilities.flat >= 0.12 && `${(probabilities.flat * 100).toFixed(0)}%`}
              </div>
            )}
            {probabilities.down > 0 && (
              <div
                className="h-full flex items-center justify-center text-[10px] font-medium text-white transition-all"
                style={{
                  width: `${Math.max(probabilities.down * 100, 2)}%`,
                  backgroundColor: PROB_COLORS.down,
                }}
                title={`跌: ${(probabilities.down * 100).toFixed(1)}%`}
              >
                {probabilities.down >= 0.12 && `${(probabilities.down * 100).toFixed(0)}%`}
              </div>
            )}
          </div>

          {/* Legend */}
          <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
            {(["up", "flat", "down"] as const).map((dir) => (
              <span key={dir} className="flex items-center gap-1">
                <span
                  className="inline-block w-2 h-2 rounded-full"
                  style={{ backgroundColor: PROB_COLORS[dir] }}
                />
                {PROB_LABELS[dir]} {(probabilities[dir] * 100).toFixed(1)}%
              </span>
            ))}
          </div>
        </div>

        {/* Interpretation */}
        <p
          className="text-xs leading-relaxed"
          style={{ color: PROB_COLORS[dominant] }}
        >
          {interpretation}
        </p>

        {/* Footer: sample count + data sufficiency */}
        <div className="flex items-center justify-between text-[10px] text-muted-foreground">
          <span>历史样本: {sample_count} 次</span>
          {!data_sufficient && (
            <span className="text-warning">样本不足</span>
          )}
        </div>

        {/* Collapsible analogy section */}
        <CollapsibleContent>
          <div className="border-t pt-2 mt-1">
            <p className="text-xs text-muted-foreground leading-relaxed">
              <span className="font-medium text-foreground/80">通俗解读: </span>
              {analogy}
            </p>
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  )
}
