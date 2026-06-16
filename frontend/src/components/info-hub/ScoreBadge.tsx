/** Score badge — shows ContentScore [0-100] with color coding and tooltip breakdown. */

import { cn } from "@/lib/utils"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"

interface ScoreBadgeProps {
  score: number | null
  explain?: Record<string, unknown>
}

function getScoreColor(score: number): string {
  if (score >= 70) return "bg-green-500/15 text-green-400 border-green-500/30"
  if (score >= 40) return "bg-yellow-500/15 text-yellow-400 border-yellow-500/30"
  return "bg-muted text-muted-foreground border-border"
}

function formatExplain(explain: Record<string, unknown>): string {
  const lines: string[] = []
  const components = ["source_weight", "timeliness", "domain_relevance", "quality_signals", "noise_penalty"] as const
  for (const key of components) {
    const comp = explain[key] as Record<string, number> | undefined
    if (comp?.points != null) {
      const label = key === "noise_penalty" ? `${key} (-)` : key
      lines.push(`${label}: ${comp.points.toFixed(1)}`)
    }
  }
  return lines.join("\n")
}

export function ScoreBadge({ score, explain }: ScoreBadgeProps) {
  if (score == null) return null

  const badge = (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-1.5 py-0 text-[10px] font-medium tabular-nums",
        getScoreColor(score),
      )}
    >
      {Math.round(score)}
    </span>
  )

  if (!explain || Object.keys(explain).length === 0) return badge

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>{badge}</TooltipTrigger>
        <TooltipContent side="top" className="whitespace-pre text-[10px] font-mono max-w-[240px]">
          {formatExplain(explain)}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}
