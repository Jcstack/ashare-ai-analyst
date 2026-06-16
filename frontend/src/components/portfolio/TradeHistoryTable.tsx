import { Link } from "react-router-dom"
import { formatTime } from "@/lib/formatters"
import { Badge } from "@/components/ui/badge"
import type { Trade } from "@/api/trade"

const ACTION_MAP: Record<string, { label: string; variant: "up" | "down" }> = {
  buy: { label: "买入", variant: "up" },
  add: { label: "加仓", variant: "up" },
  sell: { label: "卖出", variant: "down" },
  reduce: { label: "减仓", variant: "down" },
}


interface Props {
  trades: Trade[]
}

export function TradeHistoryTable({ trades }: Props) {
  if (trades.length === 0) {
    return (
      <p className="text-sm text-muted-foreground text-center py-8">
        暂无交易记录
      </p>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-xs text-muted-foreground">
            <th className="text-left py-2 px-3 font-medium">时间</th>
            <th className="text-left py-2 px-3 font-medium">股票</th>
            <th className="text-left py-2 px-3 font-medium">操作</th>
            <th className="text-right py-2 px-3 font-medium">数量</th>
            <th className="text-right py-2 px-3 font-medium">价格</th>
            <th className="text-right py-2 px-3 font-medium">金额</th>
            <th className="text-left py-2 px-3 font-medium">来源</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => {
            const act = ACTION_MAP[t.action] ?? { label: t.action, variant: "up" as const }
            return (
              <tr key={t.id} className="border-b last:border-0 hover:bg-bg-hover/50 transition-colors">
                <td className="py-2 px-3 text-muted-foreground whitespace-nowrap">
                  {formatTime(t.executed_at ?? t.created_at)}
                </td>
                <td className="py-2 px-3">
                  <Link
                    to={`/stock/${t.symbol}?from=portfolio`}
                    className="hover:text-accent-primary transition-colors"
                  >
                    <span className="font-medium">{t.stock_name}</span>
                    <span className="text-xs text-muted-foreground ml-1">{t.symbol}</span>
                  </Link>
                </td>
                <td className="py-2 px-3">
                  <Badge variant={act.variant}>{act.label}</Badge>
                </td>
                <td className="py-2 px-3 text-right font-numeric">{t.shares}</td>
                <td className="py-2 px-3 text-right font-numeric">{t.price.toFixed(2)}</td>
                <td className="py-2 px-3 text-right font-numeric">{t.amount.toFixed(2)}</td>
                <td className="py-2 px-3">
                  <Badge variant={t.source === "agent" ? "secondary" : "outline"}>
                    {t.source === "agent" ? "AI推荐" : "手动"}
                  </Badge>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
