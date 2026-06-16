import { Badge } from "@/components/ui/badge"
import { SIGNAL_COLORS, SIGNAL_LABELS } from "@/lib/constants"

interface SignalBadgeProps {
  signal: string
}

export function SignalBadge({ signal }: SignalBadgeProps) {
  const key = signal.toLowerCase()
  const color = SIGNAL_COLORS[key as keyof typeof SIGNAL_COLORS] ?? "#78909C"
  const label = SIGNAL_LABELS[key] ?? signal

  return (
    <Badge style={{ backgroundColor: color, color: "white" }} className="text-sm px-3 py-1">
      {label}
    </Badge>
  )
}
