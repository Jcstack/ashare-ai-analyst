import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Loader2 } from "lucide-react"
import type { TradingProfile } from "@/api/trade"

interface Props {
  profile: TradingProfile | undefined
  isLoading: boolean
}

export function TradingProfileStats({ profile, isLoading }: Props) {
  if (isLoading) {
    return (
      <Card>
        <CardContent className="py-6 flex items-center justify-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          加载交易画像...
        </CardContent>
      </Card>
    )
  }

  if (!profile || profile.total_trades === 0) return null

  const stats = [
    { label: "总交易数", value: String(profile.total_trades) },
    { label: "胜率", value: `${(profile.win_rate * 100).toFixed(1)}%` },
    { label: "平均持仓", value: `${profile.avg_holding_days.toFixed(1)} 天` },
    { label: "AI采纳率", value: `${(profile.agent_adoption_rate * 100).toFixed(1)}%` },
  ]

  return (
    <Card>
      <CardContent className="px-4 py-3 space-y-3">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {stats.map((s) => (
            <div key={s.label}>
              <p className="text-xs text-muted-foreground">{s.label}</p>
              <p className="text-lg font-bold mt-0.5 font-numeric">{s.value}</p>
            </div>
          ))}
        </div>

        {(profile.common_biases.length > 0 || profile.preferred_sectors.length > 0) && (
          <div className="flex flex-wrap gap-1.5">
            {profile.common_biases.map((b) => (
              <Badge key={b} variant="warning">{b}</Badge>
            ))}
            {profile.preferred_sectors.map((s) => (
              <Badge key={s} variant="secondary">{s}</Badge>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
