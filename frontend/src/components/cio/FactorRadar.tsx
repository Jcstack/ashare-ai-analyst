/** Factor Exposure Radar — SVG radar chart for 6-dimensional factor exposure (FR-QL003). */

import { useCallback, useMemo } from "react"
import { Activity } from "lucide-react"

interface FactorData {
  label: string
  value: number // 0-1
  benchmark?: number // 0-1
}

interface FactorRadarProps {
  factors: FactorData[]
  title?: string
  size?: number
}

const DEFAULT_FACTORS: FactorData[] = [
  { label: "动量", value: 0.5, benchmark: 0.5 },
  { label: "价值", value: 0.5, benchmark: 0.5 },
  { label: "波动", value: 0.5, benchmark: 0.5 },
  { label: "流动性", value: 0.5, benchmark: 0.5 },
  { label: "质量", value: 0.5, benchmark: 0.5 },
  { label: "规模", value: 0.5, benchmark: 0.5 },
]

function polarToCartesian(
  cx: number,
  cy: number,
  r: number,
  angleRad: number,
): [number, number] {
  return [cx + r * Math.cos(angleRad), cy + r * Math.sin(angleRad)]
}

function RadarPolygon({
  values,
  cx,
  cy,
  maxR,
  color,
  fillOpacity,
}: {
  values: number[]
  cx: number
  cy: number
  maxR: number
  color: string
  fillOpacity: number
}) {
  const n = values.length
  const points = values
    .map((v, i) => {
      const angle = (Math.PI * 2 * i) / n - Math.PI / 2
      const [x, y] = polarToCartesian(cx, cy, maxR * v, angle)
      return `${x},${y}`
    })
    .join(" ")

  return (
    <polygon
      points={points}
      fill={color}
      fillOpacity={fillOpacity}
      stroke={color}
      strokeWidth={1.5}
    />
  )
}

export function FactorRadar({
  factors = DEFAULT_FACTORS,
  title = "因子暴露雷达",
  size = 220,
}: FactorRadarProps) {
  const cx = size / 2
  const cy = size / 2
  const maxR = size * 0.38
  const n = factors.length
  const rings = [0.25, 0.5, 0.75, 1.0]

  const angleFor = useCallback(
    (i: number) => (Math.PI * 2 * i) / n - Math.PI / 2,
    [n],
  )

  const hasBenchmark = useMemo(
    () => factors.some((f) => f.benchmark !== undefined),
    [factors],
  )

  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="flex items-center gap-2 mb-3">
        <Activity className="h-4 w-4 text-primary" />
        <h3 className="text-sm font-medium">{title}</h3>
      </div>

      <div className="flex justify-center">
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
          {/* Grid rings */}
          {rings.map((r) => (
            <polygon
              key={r}
              points={Array.from({ length: n }, (_, i) => {
                const [x, y] = polarToCartesian(cx, cy, maxR * r, angleFor(i))
                return `${x},${y}`
              }).join(" ")}
              fill="none"
              stroke="currentColor"
              strokeOpacity={0.1}
              strokeWidth={1}
            />
          ))}

          {/* Axis lines */}
          {factors.map((_, i) => {
            const [x, y] = polarToCartesian(cx, cy, maxR, angleFor(i))
            return (
              <line
                key={i}
                x1={cx}
                y1={cy}
                x2={x}
                y2={y}
                stroke="currentColor"
                strokeOpacity={0.15}
                strokeWidth={1}
              />
            )
          })}

          {/* Benchmark polygon */}
          {hasBenchmark && (
            <RadarPolygon
              values={factors.map((f) => f.benchmark ?? 0.5)}
              cx={cx}
              cy={cy}
              maxR={maxR}
              color="var(--muted-foreground, #888)"
              fillOpacity={0.05}
            />
          )}

          {/* Data polygon */}
          <RadarPolygon
            values={factors.map((f) => f.value)}
            cx={cx}
            cy={cy}
            maxR={maxR}
            color="var(--primary, hsl(221, 83%, 53%))"
            fillOpacity={0.15}
          />

          {/* Data points */}
          {factors.map((f, i) => {
            const [x, y] = polarToCartesian(cx, cy, maxR * f.value, angleFor(i))
            return <circle key={i} cx={x} cy={y} r={3} fill="var(--primary, hsl(221, 83%, 53%))" />
          })}

          {/* Labels */}
          {factors.map((f, i) => {
            const labelR = maxR + 16
            const [x, y] = polarToCartesian(cx, cy, labelR, angleFor(i))
            return (
              <text
                key={i}
                x={x}
                y={y}
                textAnchor="middle"
                dominantBaseline="middle"
                className="fill-muted-foreground"
                fontSize={11}
              >
                {f.label}
              </text>
            )
          })}
        </svg>
      </div>

      {/* Legend */}
      <div className="flex justify-center gap-4 mt-2 text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <span
            className="inline-block w-3 h-2 rounded-sm"
            style={{ background: "var(--primary, hsl(221, 83%, 53%))", opacity: 0.6 }}
          />
          组合
        </span>
        {hasBenchmark && (
          <span className="flex items-center gap-1">
            <span
              className="inline-block w-3 h-2 rounded-sm"
              style={{ background: "var(--muted-foreground, #888)", opacity: 0.3 }}
            />
            基准
          </span>
        )}
      </div>
    </div>
  )
}
