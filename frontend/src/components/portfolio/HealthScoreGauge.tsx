import { HEALTH_COLORS } from "@/lib/constants"

interface Props {
  score: number
  label: string
}

function getScoreColor(score: number): string {
  if (score >= 80) return HEALTH_COLORS.excellent
  if (score >= 60) return HEALTH_COLORS.good
  if (score >= 40) return HEALTH_COLORS.fair
  return HEALTH_COLORS.poor
}

export function HealthScoreGauge({ score, label }: Props) {
  const color = getScoreColor(score)
  const radius = 40
  const strokeWidth = 6
  const circumference = 2 * Math.PI * radius
  const progress = (score / 100) * circumference
  const dashOffset = circumference - progress

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width="100" height="100" viewBox="0 0 100 100">
        {/* Background circle */}
        <circle
          cx="50"
          cy="50"
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          className="text-muted/30"
        />
        {/* Progress arc */}
        <circle
          cx="50"
          cy="50"
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          transform="rotate(-90 50 50)"
          className="transition-all duration-700"
        />
        {/* Score text */}
        <text
          x="50"
          y="48"
          textAnchor="middle"
          dominantBaseline="middle"
          className="text-xl font-bold"
          fill={color}
        >
          {score}
        </text>
        <text
          x="50"
          y="64"
          textAnchor="middle"
          dominantBaseline="middle"
          className="text-[10px]"
          fill="currentColor"
          opacity={0.5}
        >
          / 100
        </text>
      </svg>
      <span className="text-sm font-medium" style={{ color }}>
        {label}
      </span>
    </div>
  )
}
