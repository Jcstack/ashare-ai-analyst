import { Card, CardContent } from "@/components/ui/card"
import { MARKET_COLORS } from "@/lib/constants"
import { formatPrice, formatPercent } from "@/lib/utils"
import type { PortfolioSummary } from "@/types/portfolio"

interface Props {
  summary: PortfolioSummary
}

export function PortfolioSummaryCards({ summary }: Props) {
  const pnlColor = summary.totalPnL > 0
    ? MARKET_COLORS.up
    : summary.totalPnL < 0
      ? MARKET_COLORS.down
      : MARKET_COLORS.flat

  const cards = [
    {
      label: "总市值",
      value: `¥${formatPrice(summary.totalMarketValue)}`,
      color: undefined,
    },
    {
      label: "总盈亏",
      value: `${summary.totalPnL >= 0 ? "+" : ""}¥${formatPrice(Math.abs(summary.totalPnL))}`,
      color: pnlColor,
    },
    {
      label: "收益率",
      value: formatPercent(summary.totalPnLPercent),
      color: pnlColor,
    },
    {
      label: "持仓数",
      value: `${summary.positionCount} 只`,
      color: undefined,
    },
  ]

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {cards.map((card) => (
        <Card key={card.label}>
          <CardContent className="p-4">
            <p className="text-xs text-muted-foreground">{card.label}</p>
            <p
              className="text-xl font-bold mt-1 font-numeric"
              style={card.color ? { color: card.color } : undefined}
            >
              {card.value}
            </p>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
