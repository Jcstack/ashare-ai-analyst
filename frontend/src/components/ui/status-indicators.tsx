import { cn } from "@/lib/utils"
import { TrendingUp, TrendingDown, Minus } from "lucide-react"

// ── StatusDot ──────────────────────────────────────────────────────────────

type StatusLevel = "high" | "medium" | "low" | "neutral"

const DOT_COLORS: Record<StatusLevel, string> = {
  high: "bg-up",
  medium: "bg-warning",
  low: "bg-down",
  neutral: "bg-flat",
}

const DOT_LABELS: Record<StatusLevel, string> = {
  high: "高",
  medium: "中",
  low: "低",
  neutral: "—",
}

interface StatusDotProps {
  level: StatusLevel
  size?: "sm" | "md"
  showLabel?: boolean
  label?: string
  className?: string
}

/**
 * Colored dot indicator — replaces emoji 🔴🟡⚪ in data display.
 * Uses semantic colors via CSS variables.
 */
export function StatusDot({ level, size = "sm", showLabel = false, label, className }: StatusDotProps) {
  const dotSize = size === "sm" ? "h-2 w-2" : "h-2.5 w-2.5"
  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      <span className={cn("rounded-full shrink-0", dotSize, DOT_COLORS[level])} />
      {showLabel && (
        <span className="text-xs text-text-secondary">{label ?? DOT_LABELS[level]}</span>
      )}
    </span>
  )
}

// ── TrendArrow ─────────────────────────────────────────────────────────────

type TrendDirection = "up" | "down" | "neutral"

interface TrendArrowProps {
  direction: TrendDirection
  size?: number
  className?: string
}

/**
 * Trend direction indicator — replaces ↑↓→ and ▲▼● in data display.
 * Uses lucide icons with semantic colors.
 */
export function TrendArrow({ direction, size = 12, className }: TrendArrowProps) {
  if (direction === "up") {
    return <TrendingUp style={{ width: size, height: size, color: "var(--semantic-up)" }} className={className} />
  }
  if (direction === "down") {
    return <TrendingDown style={{ width: size, height: size, color: "var(--semantic-down)" }} className={className} />
  }
  return <Minus style={{ width: size, height: size, color: "var(--semantic-flat)" }} className={className} />
}
