import { Badge } from "@/components/ui/badge"
import { RISK_COLORS, RISK_LABELS } from "@/lib/constants"

interface RiskBadgeProps {
  level: string
}

export function RiskBadge({ level }: RiskBadgeProps) {
  const key = level.toLowerCase()
  const color = RISK_COLORS[key as keyof typeof RISK_COLORS] ?? "#78909C"
  const label = RISK_LABELS[key] ?? level

  return (
    <Badge style={{ backgroundColor: color, color: "white" }} className="text-sm px-3 py-1">
      {label}
    </Badge>
  )
}
