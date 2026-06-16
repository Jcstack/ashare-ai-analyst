/** Cross-verification badge — displays source verification level with color coding. */

import { Check } from "lucide-react"
import { cn } from "@/lib/utils"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"

interface CrossVerificationBadgeProps {
  score: number // 0.0-1.0
  sources: number
}

function getVerificationLevel(score: number): {
  color: string
  dotColor: string
  label: string
  showCheck: boolean
  tooltip: string
} {
  if (score >= 0.8) {
    return {
      color: "text-emerald-400",
      dotColor: "bg-emerald-400",
      label: "多源验证",
      showCheck: true,
      tooltip: "多个独立来源交叉验证，可信度高",
    }
  }
  if (score >= 0.5) {
    return {
      color: "text-green-400",
      dotColor: "bg-green-400",
      label: "3源验证",
      showCheck: false,
      tooltip: "3个来源交叉验证",
    }
  }
  if (score >= 0.2) {
    return {
      color: "text-blue-400",
      dotColor: "bg-blue-400",
      label: "2源验证",
      showCheck: false,
      tooltip: "2个来源报道此事件",
    }
  }
  return {
    color: "text-muted-foreground",
    dotColor: "bg-muted-foreground",
    label: "单源",
    showCheck: false,
    tooltip: "仅单一来源，尚无交叉验证",
  }
}

export function CrossVerificationBadge({ score, sources }: CrossVerificationBadgeProps) {
  const level = getVerificationLevel(score)

  const badge = (
    <span className={cn("inline-flex items-center gap-1.5 text-[11px] font-medium", level.color)}>
      <span className={cn("h-2 w-2 rounded-full shrink-0", level.dotColor)} />
      {level.label}
      {level.showCheck && <Check className="h-3 w-3" />}
    </span>
  )

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>{badge}</TooltipTrigger>
        <TooltipContent side="top" className="text-xs max-w-[200px]">
          <p>{level.tooltip}</p>
          <p className="text-muted-foreground mt-1">
            验证分: {(score * 100).toFixed(0)} | {sources}个源
          </p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}
