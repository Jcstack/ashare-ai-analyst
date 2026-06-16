/** Current trading phase badge — small, embeddable in Dashboard header. */

import { Badge } from "@/components/ui/badge"
import { usePhaseInfo } from "@/hooks/useMarketIntelligence"
import { MARKET_PHASE_LABELS } from "@/types/intelligence"
import type { MarketPhase } from "@/types/intelligence"

const PHASE_STYLES: Partial<Record<MarketPhase, string>> = {
  MORNING: "border-green-500/30 text-green-500",
  AFTERNOON: "border-green-500/30 text-green-500",
  CALL_AUCTION: "border-yellow-500/30 text-yellow-500",
  CLOSING_AUCTION: "border-yellow-500/30 text-yellow-500",
  MIDDAY_BREAK: "border-muted-foreground/30 text-muted-foreground",
  PRE_OPEN: "border-blue-500/30 text-blue-500",
  POST_CLOSE: "border-muted-foreground/30 text-muted-foreground",
  CLOSED: "border-muted-foreground/30 text-muted-foreground",
}

export function PhaseIndicator() {
  const { data: phaseInfo } = usePhaseInfo()

  if (!phaseInfo) return null

  const label = MARKET_PHASE_LABELS[phaseInfo.phase] ?? phaseInfo.phase
  const style = PHASE_STYLES[phaseInfo.phase] ?? ""

  return (
    <Badge variant="outline" className={`text-xs h-6 gap-1 ${style}`}>
      {label}
    </Badge>
  )
}
