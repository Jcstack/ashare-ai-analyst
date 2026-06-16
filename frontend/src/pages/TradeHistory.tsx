/** Trade History page — shows trade log and trading behavior profile. */

import { useState } from "react"
import { Link } from "react-router-dom"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useTradeHistory, useTradingProfile } from "@/hooks/useTrades"
import { History, ArrowRight, Loader2, Search } from "lucide-react"
import type { Trade } from "@/api/trade"

const ACTION_CONFIG: Record<string, { label: string; variant: "default" | "destructive" | "secondary" | "outline" }> = {
  buy: { label: "买入", variant: "default" },
  sell: { label: "卖出", variant: "destructive" },
  add: { label: "加仓", variant: "default" },
  reduce: { label: "减仓", variant: "secondary" },
}

function TradeRow({ trade }: { trade: Trade }) {
  const cfg = ACTION_CONFIG[trade.action] ?? { label: trade.action, variant: "outline" as const }
  const date = trade.executed_at ?? trade.created_at
  const formattedDate = date ? new Date(date).toLocaleString("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }) : "-"

  return (
    <tr className="border-b border-border/50 last:border-0 hover:bg-muted/30 transition-colors">
      <td className="py-2.5 px-2">
        <span className="text-[10px] text-muted-foreground font-numeric">{formattedDate}</span>
      </td>
      <td className="py-2.5 px-2">
        <Link
          to={`/stock/${trade.symbol}`}
          className="hover:text-primary transition-colors"
        >
          <span className="font-medium">{trade.stock_name}</span>
          <span className="text-muted-foreground ml-1 text-[10px]">{trade.symbol}</span>
        </Link>
      </td>
      <td className="py-2.5 px-2 text-center">
        <Badge variant={cfg.variant} className="text-[10px]">{cfg.label}</Badge>
      </td>
      <td className="py-2.5 px-2 text-right font-numeric">{trade.shares}</td>
      <td className="py-2.5 px-2 text-right font-numeric">{trade.price.toFixed(2)}</td>
      <td className="py-2.5 px-2 text-right font-numeric">{trade.amount.toFixed(0)}</td>
      <td className="py-2.5 px-2 text-center">
        <Badge variant="outline" className="text-[10px]">
          {trade.source === "agent" ? "AI" : "手动"}
        </Badge>
      </td>
      <td className="py-2.5 px-2 text-[10px] text-muted-foreground max-w-[200px] truncate">
        {trade.reasoning || "-"}
      </td>
    </tr>
  )
}

function ProfileCard() {
  const { data: profile, isLoading } = useTradingProfile()

  if (isLoading || !profile) return null

  return (
    <Card>
      <CardContent className="py-4 px-5">
        <div className="flex items-center justify-between mb-3">
          <span className="text-caption font-medium">交易画像</span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
          <div>
            <span className="text-muted-foreground">总交易</span>
            <p className="font-numeric text-lg">{profile.total_trades}</p>
          </div>
          <div>
            <span className="text-muted-foreground">胜率</span>
            <p className={`font-numeric text-lg ${profile.win_rate >= 50 ? "text-market-up" : "text-market-down"}`}>
              {profile.win_rate.toFixed(1)}%
            </p>
          </div>
          <div>
            <span className="text-muted-foreground">平均持仓</span>
            <p className="font-numeric text-lg">{profile.avg_holding_days.toFixed(1)}天</p>
          </div>
          <div>
            <span className="text-muted-foreground">AI采纳率</span>
            <p className="font-numeric text-lg">{(profile.agent_adoption_rate * 100).toFixed(0)}%</p>
          </div>
        </div>
        {profile.common_biases.length > 0 && (
          <div className="mt-3 flex gap-1.5 flex-wrap">
            <span className="text-[10px] text-muted-foreground">行为偏差:</span>
            {profile.common_biases.map((b) => (
              <Badge key={b} variant="secondary" className="text-[10px]">{b}</Badge>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export default function TradeHistory() {
  const [filterSymbol, setFilterSymbol] = useState("")
  const [limit, setLimit] = useState(50)
  const { data, isLoading, error } = useTradeHistory(filterSymbol || undefined, limit)

  const trades = data?.trades ?? []
  const total = data?.total ?? 0

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <History className="h-5 w-5 text-primary" />
        <h1 className="text-headline">交易记录</h1>
      </div>

      <ProfileCard />

      <Card>
        <CardContent className="py-4 px-5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-caption font-medium">
              交易历史 {total > 0 && <span className="text-muted-foreground font-normal">({total} 笔)</span>}
            </span>
            <div className="flex items-center gap-2">
              <div className="relative">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
                <Input
                  placeholder="按股票代码筛选"
                  value={filterSymbol}
                  onChange={(e) => setFilterSymbol(e.target.value)}
                  className="w-36 h-7 text-xs pl-7"
                />
              </div>
            </div>
          </div>

          {isLoading && (
            <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground py-8">
              <Loader2 className="h-3 w-3 animate-spin" />
              加载交易记录...
            </div>
          )}

          {error && (
            <p className="text-xs text-destructive">加载失败: {error.message}</p>
          )}

          {!isLoading && trades.length === 0 && (
            <div className="text-center py-8 text-xs text-muted-foreground space-y-2">
              <p>暂无交易记录</p>
              <Link
                to="/portfolio"
                className="inline-flex items-center gap-1 text-primary hover:text-primary/80 transition-colors"
              >
                前往投资管理 <ArrowRight className="h-3 w-3" />
              </Link>
            </div>
          )}

          {trades.length > 0 && (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-muted-foreground border-b">
                      <th className="text-left py-1.5 px-2 font-medium">时间</th>
                      <th className="text-left py-1.5 px-2 font-medium">标的</th>
                      <th className="text-center py-1.5 px-2 font-medium">方向</th>
                      <th className="text-right py-1.5 px-2 font-medium">数量</th>
                      <th className="text-right py-1.5 px-2 font-medium">价格</th>
                      <th className="text-right py-1.5 px-2 font-medium">金额</th>
                      <th className="text-center py-1.5 px-2 font-medium">来源</th>
                      <th className="text-left py-1.5 px-2 font-medium">理由</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.map((trade) => (
                      <TradeRow key={trade.id} trade={trade} />
                    ))}
                  </tbody>
                </table>
              </div>

              {total > trades.length && (
                <div className="text-center">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setLimit((l) => l + 50)}
                    className="text-xs"
                  >
                    加载更多 ({total - trades.length} 笔)
                  </Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
