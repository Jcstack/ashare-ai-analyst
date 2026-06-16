import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { ChevronDown, ChevronUp, Bell, AlertTriangle, Info } from "lucide-react"
import { ALERT_COLORS } from "@/lib/constants"
import type { Alert } from "@/types/agent"

const SEVERITY_ICON = {
  critical: AlertTriangle,
  warning: AlertTriangle,
  info: Info,
} as const

const SEVERITY_ORDER: Record<string, number> = {
  critical: 0,
  warning: 1,
  info: 2,
}

function usePortfolioAlerts(symbols: string[]) {
  return useQuery({
    queryKey: ["portfolio-alerts", symbols.join(",")],
    queryFn: async () => {
      const results = await Promise.allSettled(
        symbols.slice(0, 20).map(async (sym) => {
          try {
            const res = await fetch(`/api/v1/stock/${sym}/alerts`)
            if (!res.ok) return []
            return (await res.json()) as Alert[]
          } catch {
            return []
          }
        })
      )
      const all: Alert[] = []
      for (const r of results) {
        if (r.status === "fulfilled") all.push(...r.value)
      }
      all.sort(
        (a, b) =>
          (SEVERITY_ORDER[a.severity] ?? 2) - (SEVERITY_ORDER[b.severity] ?? 2)
      )
      return all.slice(0, 5)
    },
    enabled: symbols.length > 0,
    staleTime: 2 * 60 * 1000,
    refetchInterval: 60 * 1000,
    retry: 0,
  })
}

interface Props {
  symbols: string[]
}

export function SmartAlerts({ symbols }: Props) {
  const { data: alerts, isLoading } = usePortfolioAlerts(symbols)
  const [expanded, setExpanded] = useState(true)
  const navigate = useNavigate()

  if (!alerts || alerts.length === 0) {
    if (isLoading) return null
    return null
  }

  return (
    <Card className="border-warning/20 overflow-hidden">
      <CardContent className="p-4">
        <button
          className="flex items-center justify-between w-full text-left"
          onClick={() => setExpanded(!expanded)}
        >
          <div className="flex items-center gap-2">
            <Bell className="h-4 w-4 text-warning" />
            <span className="text-title">持仓预警</span>
            <Badge variant="outline" className="text-xs border-warning/30 text-warning">
              {alerts.length}
            </Badge>
          </div>
          {expanded ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
        </button>

        {expanded && (
          <div className="mt-3 space-y-2">
            {alerts.map((alert) => {
              const Icon = SEVERITY_ICON[alert.severity as keyof typeof SEVERITY_ICON] ?? Info
              const color = ALERT_COLORS[alert.severity as keyof typeof ALERT_COLORS] ?? ALERT_COLORS.info

              return (
                <button
                  key={alert.id}
                  className="flex items-start gap-2 w-full text-left rounded-md px-2 py-1.5 hover:bg-accent/50 transition-colors"
                  onClick={() => navigate(`/stock/${alert.symbol}`)}
                >
                  <Icon className="h-3.5 w-3.5 mt-0.5 flex-shrink-0" style={{ color }} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <Badge variant="secondary" className="text-[10px] px-1 py-0">
                        {alert.name}
                      </Badge>
                      <span className="text-xs font-medium truncate">{alert.title}</span>
                    </div>
                    <p className="text-xs text-muted-foreground truncate mt-0.5">
                      {alert.description}
                    </p>
                  </div>
                </button>
              )
            })}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
