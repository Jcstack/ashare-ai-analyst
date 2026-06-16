/** Source health table — displays all intelligence sources with status indicators. */

import { Badge } from "@/components/ui/badge"
import type { SourceHealth } from "@/types/info-hub"

const LAYER_COLORS: Record<string, string> = {
  L1: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  L2: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  L3: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  L4: "bg-muted text-muted-foreground border-border",
  L5: "bg-rose-500/15 text-rose-400 border-rose-500/30",
}

const STATUS_COLORS: Record<string, string> = {
  OK: "bg-green-500",
  WARN: "bg-yellow-500",
  DOWN: "bg-red-500",
}

const STATUS_LABELS: Record<string, string> = {
  OK: "正常",
  WARN: "告警",
  DOWN: "离线",
}

const COMPLIANCE_COLORS: Record<string, string> = {
  HIGH: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  MEDIUM: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  LOW: "bg-rose-500/15 text-rose-400 border-rose-500/30",
}

function formatSourceId(id: string): string {
  return id
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

interface SourceHealthTableProps {
  sources: SourceHealth[]
}

export function SourceHealthTable({ sources }: SourceHealthTableProps) {
  const sorted = [...sources].sort((a, b) => {
    if (a.layer !== b.layer) return a.layer.localeCompare(b.layer)
    const statusOrder: Record<string, number> = { DOWN: 0, WARN: 1, OK: 2 }
    return (statusOrder[a.status] ?? 2) - (statusOrder[b.status] ?? 2)
  })

  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-bg-elevated">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted-foreground">
            <th className="px-4 py-3 font-medium">源</th>
            <th className="px-4 py-3 font-medium">层级</th>
            <th className="px-4 py-3 font-medium">状态</th>
            <th className="px-4 py-3 font-medium text-right">权重</th>
            <th className="px-4 py-3 font-medium text-right">有效权重</th>
            <th className="px-4 py-3 font-medium">合规</th>
            <th className="px-4 py-3 font-medium text-right">延迟</th>
            <th className="px-4 py-3 font-medium text-right">失败</th>
            <th className="px-4 py-3 font-medium">领域</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((source) => {
            const weightDimmed = source.effective_weight !== source.base_weight
            return (
              <tr
                key={source.source_id}
                className="border-b border-border/50 transition-colors hover:bg-bg-hover"
              >
                {/* Source ID */}
                <td className="px-4 py-3 font-medium text-foreground">
                  {formatSourceId(source.source_id)}
                </td>

                {/* Layer */}
                <td className="px-4 py-3">
                  <Badge
                    variant="outline"
                    className={LAYER_COLORS[source.layer] ?? LAYER_COLORS.L4}
                  >
                    {source.layer}
                  </Badge>
                </td>

                {/* Status */}
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span
                      className={`inline-block h-2 w-2 rounded-full ${STATUS_COLORS[source.status] ?? STATUS_COLORS.DOWN}`}
                    />
                    <span className="text-muted-foreground">
                      {STATUS_LABELS[source.status] ?? source.status}
                    </span>
                  </div>
                </td>

                {/* Base Weight */}
                <td className="px-4 py-3 text-right tabular-nums text-foreground">
                  {source.base_weight.toFixed(2)}
                </td>

                {/* Effective Weight */}
                <td
                  className={`px-4 py-3 text-right tabular-nums ${
                    weightDimmed ? "text-muted-foreground" : "text-foreground"
                  }`}
                >
                  {source.effective_weight.toFixed(2)}
                </td>

                {/* Compliance */}
                <td className="px-4 py-3">
                  <Badge
                    variant="outline"
                    className={COMPLIANCE_COLORS[source.compliance_level] ?? COMPLIANCE_COLORS.LOW}
                  >
                    {source.compliance_level}
                  </Badge>
                </td>

                {/* Latency */}
                <td className="px-4 py-3 text-right tabular-nums text-muted-foreground">
                  {Math.round(source.avg_latency_ms)}ms
                </td>

                {/* Failures */}
                <td
                  className={`px-4 py-3 text-right tabular-nums ${
                    source.consecutive_failures > 0
                      ? "text-red-400 font-medium"
                      : "text-muted-foreground"
                  }`}
                >
                  {source.consecutive_failures}
                </td>

                {/* Domain Tags */}
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1">
                    {source.domain_tags.map((tag) => (
                      <Badge
                        key={tag}
                        variant="secondary"
                        className="text-[10px] px-1.5 py-0"
                      >
                        {tag}
                      </Badge>
                    ))}
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {sorted.length === 0 && (
        <div className="px-4 py-8 text-center text-sm text-muted-foreground">
          暂无源数据
        </div>
      )}
    </div>
  )
}
