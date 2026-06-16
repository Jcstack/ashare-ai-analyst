import { useNavigate } from "react-router-dom"
import { Briefcase, Sparkles, ArrowRight } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { MARKET_COLORS } from "@/lib/constants"
import { formatPrice, formatPercent } from "@/lib/utils"
import type { PortfolioSummary } from "@/types/portfolio"

interface Props {
  summary: PortfolioSummary
}

export function PortfolioMiniCard({ summary }: Props) {
  const navigate = useNavigate()

  const pnlColor = summary.totalPnL > 0
    ? MARKET_COLORS.up
    : summary.totalPnL < 0
      ? MARKET_COLORS.down
      : MARKET_COLORS.flat

  return (
    <Card>
      <CardContent className="p-3 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Briefcase className="h-4 w-4 text-primary" />
            <span className="text-title">我的持仓</span>
          </div>
          <span className="text-xs text-muted-foreground">{summary.positionCount} 只</span>
        </div>

        <div className="space-y-1">
          <p className="text-lg font-bold font-numeric">
            ¥{formatPrice(summary.totalMarketValue)}
          </p>
          <p className="text-sm font-numeric" style={{ color: pnlColor }}>
            {summary.totalPnL >= 0 ? "+" : ""}¥{formatPrice(Math.abs(summary.totalPnL))}
            <span className="ml-1.5 text-xs">
              ({formatPercent(summary.totalPnLPercent)})
            </span>
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            className="flex-1 h-7 text-xs gap-1"
            onClick={() => navigate("/portfolio")}
          >
            查看全部
            <ArrowRight className="h-3 w-3" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs gap-1 border-accent-primary/30 text-accent-primary hover:bg-accent-primary/10"
            onClick={() => navigate("/portfolio")}
          >
            <Sparkles className="h-3 w-3" />
            AI 诊断
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
