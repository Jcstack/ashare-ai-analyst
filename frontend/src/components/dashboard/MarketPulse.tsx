import { useNavigate } from "react-router-dom"
import { formatTimeShort } from "@/lib/formatters"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Activity, AlertTriangle, TrendingUp, Newspaper, BarChart3, BellOff } from "lucide-react"
import { useNotifications } from "@/hooks/useNotifications"

const TYPE_ICONS: Record<string, typeof Activity> = {
  anomaly: AlertTriangle,
  sentiment_shift: TrendingUp,
  hot_entry: BarChart3,
  market_overview: Newspaper,
}

const TYPE_COLORS: Record<string, string> = {
  anomaly: "#f59e0b",
  sentiment_shift: "var(--color-market-up)",
  hot_entry: "#8b5cf6",
  market_overview: "#3b82f6",
}

export function MarketPulse() {
  const navigate = useNavigate()
  const { data: notifications, isLoading } = useNotifications()

  const recent = (notifications ?? []).slice(0, 5)

  return (
    <Card>
      <CardHeader className="py-3 px-4">
        <CardTitle className="text-title flex items-center gap-2">
          <Activity className="h-4 w-4 text-warning" />
          市场脉搏
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-3">
        {recent.length > 0 ? (
          <div className="space-y-2">
            {recent.map((item) => {
              const Icon = TYPE_ICONS[item.type] ?? Activity
              const color = TYPE_COLORS[item.type] ?? "var(--color-market-flat)"
              const clickable = !!item.symbol

              return (
                <div
                  key={item.id}
                  className={`flex items-start gap-2 text-xs ${clickable ? "cursor-pointer hover:bg-accent rounded-md p-1 -m-1 transition-colors" : ""}`}
                  onClick={clickable ? () => navigate(`/stock/${item.symbol}`) : undefined}
                  role={clickable ? "button" : undefined}
                  tabIndex={clickable ? 0 : undefined}
                  onKeyDown={clickable ? (e) => { if (e.key === "Enter") navigate(`/stock/${item.symbol}`) } : undefined}
                >
                  <div
                    className="mt-0.5 rounded-full p-1 shrink-0"
                    style={{ backgroundColor: color + "15" }}
                  >
                    <Icon className="h-3 w-3" style={{ color }} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="font-medium truncate">{item.title}</span>
                      {item.symbol && (
                        <Badge variant="outline" className="text-[9px] px-1 py-0">{item.symbol}</Badge>
                      )}
                    </div>
                    <p className="text-muted-foreground leading-relaxed line-clamp-1 mt-0.5">{item.summary}</p>
                  </div>
                  <span className="text-[10px] text-muted-foreground shrink-0 mt-0.5">
                    {formatTimeShort(item.timestamp)}
                  </span>
                </div>
              )
            })}
          </div>
        ) : (
          <div className="flex flex-col items-center py-4 text-muted-foreground">
            <BellOff className="h-5 w-5 mb-1.5 opacity-40" />
            <p className="text-xs">
              {isLoading ? "加载中..." : "暂无市场动态，盘中将自动推送异动通知"}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
