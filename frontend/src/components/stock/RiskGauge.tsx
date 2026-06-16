interface RiskGaugeProps {
  riskLevel: "low" | "medium" | "high"
  confidence?: number
}

const RISK_CONFIG = {
  low: { angle: -60, color: "#66BB6A", label: "低风险" },
  medium: { angle: 0, color: "#FFA726", label: "中风险" },
  high: { angle: 60, color: "#EF5350", label: "高风险" },
}

export function RiskGauge({ riskLevel, confidence }: RiskGaugeProps) {
  const config = RISK_CONFIG[riskLevel] || RISK_CONFIG.medium

  return (
    <div className="flex flex-col items-center gap-1">
      <div className="risk-gauge">
        <svg viewBox="0 0 120 60" className="w-full h-full">
          {/* Background arc */}
          <path
            d="M 10 55 A 50 50 0 0 1 110 55"
            fill="none"
            stroke="currentColor"
            strokeWidth="6"
            className="text-muted/30"
          />
          {/* Green zone */}
          <path
            d="M 10 55 A 50 50 0 0 1 43 12"
            fill="none"
            stroke="#66BB6A"
            strokeWidth="6"
            opacity="0.4"
          />
          {/* Yellow zone */}
          <path
            d="M 43 12 A 50 50 0 0 1 77 12"
            fill="none"
            stroke="#FFA726"
            strokeWidth="6"
            opacity="0.4"
          />
          {/* Red zone */}
          <path
            d="M 77 12 A 50 50 0 0 1 110 55"
            fill="none"
            stroke="#EF5350"
            strokeWidth="6"
            opacity="0.4"
          />
          {/* Needle */}
          <line
            x1="60"
            y1="55"
            x2={60 + 35 * Math.cos((config.angle - 90) * Math.PI / 180)}
            y2={55 + 35 * Math.sin((config.angle - 90) * Math.PI / 180)}
            stroke={config.color}
            strokeWidth="2"
            strokeLinecap="round"
          />
          {/* Center dot */}
          <circle cx="60" cy="55" r="3" fill={config.color} />
        </svg>
      </div>
      <span className="text-xs font-medium" style={{ color: config.color }}>
        {config.label}
      </span>
      {confidence != null && (
        <span className="text-xs text-muted-foreground font-numeric">
          置信度 {Math.round(confidence * 100)}%
        </span>
      )}
    </div>
  )
}
