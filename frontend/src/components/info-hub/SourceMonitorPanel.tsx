/** Source monitoring panel — health overview, latency ranking, layer distribution. */

import { Badge } from "@/components/ui/badge"
import type { SourceHealth } from "@/types/info-hub"

const LAYER_COLORS: Record<string, string> = {
  L1: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  L2: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  L3: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  L4: "bg-muted text-muted-foreground border-border",
  L5: "bg-rose-500/15 text-rose-400 border-rose-500/30",
}

interface SourceMonitorPanelProps {
  sources: SourceHealth[]
}

export function SourceMonitorPanel({ sources }: SourceMonitorPanelProps) {
  const okCount = sources.filter((s) => s.status === "OK").length
  const warnCount = sources.filter((s) => s.status === "WARN").length
  const downCount = sources.filter((s) => s.status === "DOWN").length

  // Top 10 slowest sources for latency ranking
  const slowest = [...sources]
    .sort((a, b) => b.avg_latency_ms - a.avg_latency_ms)
    .slice(0, 10)
  const maxLatency = slowest.length > 0 ? slowest[0].avg_latency_ms : 1

  // Layer distribution
  const layerCounts: Record<string, number> = {}
  for (const s of sources) {
    layerCounts[s.layer] = (layerCounts[s.layer] ?? 0) + 1
  }
  const layerKeys = ["L1", "L2", "L3", "L4", "L5"]

  return (
    <div className="space-y-6">
      {/* Section 1: Health Overview */}
      <div>
        <h3 className="mb-3 text-sm font-medium text-foreground">健康概览</h3>
        <div className="grid grid-cols-3 gap-3">
          <HealthStatCard
            label="在线源"
            count={okCount}
            accent="green"
          />
          <HealthStatCard
            label="告警源"
            count={warnCount}
            accent="yellow"
          />
          <HealthStatCard
            label="离线源"
            count={downCount}
            accent="red"
          />
        </div>
      </div>

      {/* Section 2: Latency Ranking */}
      {slowest.length > 0 && (
        <div>
          <h3 className="mb-3 text-sm font-medium text-foreground">
            延迟排行
          </h3>
          <div className="rounded-lg border border-border bg-bg-elevated p-4 space-y-2">
            {slowest.map((source) => {
              const ratio = maxLatency > 0 ? source.avg_latency_ms / maxLatency : 0
              // Interpolate from neutral to red based on ratio
              const hue = Math.round((1 - ratio) * 30) // 30 (orange-ish) down to 0 (red)
              return (
                <div
                  key={source.source_id}
                  className="flex items-center gap-3 text-sm"
                >
                  <span className="w-36 shrink-0 truncate text-muted-foreground">
                    {formatSourceId(source.source_id)}
                  </span>
                  <div className="relative h-5 flex-1 overflow-hidden rounded bg-muted/30">
                    <div
                      className="absolute inset-y-0 left-0 rounded transition-all"
                      style={{
                        width: `${Math.max(ratio * 100, 2)}%`,
                        backgroundColor: `hsl(${hue}, 70%, 50%)`,
                        opacity: 0.3 + ratio * 0.5,
                      }}
                    />
                  </div>
                  <span className="w-16 shrink-0 text-right tabular-nums text-muted-foreground">
                    {Math.round(source.avg_latency_ms)}ms
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Section 3: Layer Distribution */}
      <div>
        <h3 className="mb-3 text-sm font-medium text-foreground">层级分布</h3>
        <div className="flex flex-wrap gap-2">
          {layerKeys.map((layer) => {
            const count = layerCounts[layer] ?? 0
            return (
              <Badge
                key={layer}
                variant="outline"
                className={`${LAYER_COLORS[layer] ?? LAYER_COLORS.L4} px-2.5 py-1 text-xs tabular-nums`}
              >
                {layer}: {count}
              </Badge>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ─── Internal components ─────────────────────────────────────────────────────

function HealthStatCard({
  label,
  count,
  accent,
}: {
  label: string
  count: number
  accent: "green" | "yellow" | "red"
}) {
  const accentClasses: Record<string, { border: string; text: string; bg: string }> = {
    green: {
      border: "border-green-500/30",
      text: "text-green-400",
      bg: "bg-green-500/5",
    },
    yellow: {
      border: "border-yellow-500/30",
      text: "text-yellow-400",
      bg: "bg-yellow-500/5",
    },
    red: {
      border: "border-red-500/30",
      text: "text-red-400",
      bg: "bg-red-500/5",
    },
  }

  const colors = accentClasses[accent]

  return (
    <div
      className={`rounded-lg border ${colors.border} ${colors.bg} px-4 py-3`}
    >
      <div className={`text-2xl font-semibold tabular-nums ${colors.text}`}>
        {count}
      </div>
      <div className="text-xs text-muted-foreground">{label}</div>
    </div>
  )
}

function formatSourceId(id: string): string {
  return id
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
}
