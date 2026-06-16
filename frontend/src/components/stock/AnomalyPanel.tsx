import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Zap } from "lucide-react"
import { useStockAnomalies } from "@/hooks/useNews"

interface AnomalyPanelProps {
  symbol: string
}

export function AnomalyPanel({ symbol }: AnomalyPanelProps) {
  const { data: anomalies, isLoading } = useStockAnomalies(symbol)

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    )
  }

  if (!anomalies || anomalies.length === 0) {
    return <p className="text-sm text-muted-foreground py-4 text-center">暂无异动记录</p>
  }

  return (
    <div className="space-y-2">
      {anomalies.map((item, i) => (
        <Card key={i}>
          <CardContent className="p-3 flex items-start gap-3">
            <div className="rounded-full bg-warning/10 p-1.5 mt-0.5">
              <Zap className="h-3.5 w-3.5 text-warning" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-0.5">
                <span className="text-xs text-muted-foreground">{item.datetime}</span>
                {item.change_type && (
                  <Badge variant="outline" className="text-[10px] px-1 py-0">{item.change_type}</Badge>
                )}
              </div>
              <p className="text-sm">{item.description || item.change_type || "异动"}</p>
              {item.sector && (
                <span className="text-xs text-muted-foreground">板块: {item.sector}</span>
              )}
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
