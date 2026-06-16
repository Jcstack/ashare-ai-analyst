import { useState } from "react"
import { Button } from "@/components/ui/button"
import { AlertTriangle, Bell, X } from "lucide-react"
import { useStockAlerts } from "@/hooks/useAlerts"
import { cn } from "@/lib/utils"

interface AlertBannerProps {
  symbol: string
}

const severityStyles: Record<string, string> = {
  critical: "bg-danger/10 border-danger/30 text-danger",
  warning: "bg-warning/10 border-warning/30 text-warning",
  info: "bg-info/10 border-info/30 text-info",
}

export function AlertBanner({ symbol }: AlertBannerProps) {
  const { data: alerts } = useStockAlerts(symbol)
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())

  const visible = (alerts ?? []).filter((a) => !dismissed.has(a.id))

  if (visible.length === 0) return null

  const critical = visible.filter((a) => a.severity === "critical")
  const others = visible.filter((a) => a.severity !== "critical")
  const display = [...critical, ...others].slice(0, 3)

  return (
    <div className="space-y-1.5">
      {display.map((alert) => (
        <div
          key={alert.id}
          className={cn("flex items-center gap-2 px-3 py-2 rounded-md border text-sm", severityStyles[alert.severity] || severityStyles.info)}
        >
          {alert.severity === "critical" ? (
            <AlertTriangle className="h-4 w-4 shrink-0" />
          ) : (
            <Bell className="h-4 w-4 shrink-0" />
          )}
          <span className="flex-1 text-sm">{alert.title}</span>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 w-6 p-0"
            onClick={() => setDismissed((prev) => new Set(prev).add(alert.id))}
          >
            <X className="h-3 w-3" />
          </Button>
        </div>
      ))}
    </div>
  )
}
