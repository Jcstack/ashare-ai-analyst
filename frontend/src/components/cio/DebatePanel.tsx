/** Bull/Bear debate panel — run adversarial analysis on a stock. */

import { useState } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Loader2, Swords } from "lucide-react"
import { useDebate } from "@/hooks/useIntelligence"
import type { DebateRecord } from "@/types/cio-dashboard"

function ScoreBar({ bull, bear }: { bull: number; bear: number }) {
  const total = bull + bear || 1
  const bullPct = (bull / total) * 100
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-[10px] text-muted-foreground">
        <span>多方 {bull.toFixed(1)}</span>
        <span>空方 {bear.toFixed(1)}</span>
      </div>
      <div className="h-2 rounded-full overflow-hidden flex bg-muted">
        <div className="bg-market-up/70 transition-all" style={{ width: `${bullPct}%` }} />
        <div className="bg-market-down/70 flex-1" />
      </div>
    </div>
  )
}

export function DebatePanel() {
  const [symbol, setSymbol] = useState("")
  const [name, setName] = useState("")
  const [record, setRecord] = useState<DebateRecord | null>(null)
  const mutation = useDebate()

  const handleRun = () => {
    if (!symbol.trim()) return
    mutation.mutate(
      { symbol: symbol.trim(), name: name.trim() || undefined, trigger: "CIO dashboard" },
      {
        onSuccess: (data) => setRecord(data),
      },
    )
  }

  return (
    <Card>
      <CardContent className="py-4 px-5 space-y-3">
        <div className="flex items-center gap-2">
          <Swords className="h-4 w-4 text-primary" />
          <span className="text-caption font-medium">多空辩论</span>
        </div>

        <div className="flex gap-2">
          <Input
            placeholder="股票代码"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            className="w-28 h-8 text-xs"
          />
          <Input
            placeholder="名称（可选）"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="flex-1 h-8 text-xs"
          />
          <Button
            size="sm"
            onClick={handleRun}
            disabled={mutation.isPending || !symbol.trim()}
            className="h-8 text-xs"
          >
            {mutation.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : "分析"}
          </Button>
        </div>

        {record && (
          <div className="space-y-3 pt-1">
            <div className="flex items-center gap-2">
              <span className="font-medium text-sm">{record.name || record.symbol}</span>
              {record.risk_veto && (
                <Badge variant="destructive" className="text-[10px]">风控否决</Badge>
              )}
              <Badge
                variant={
                  record.final_action.includes("买") ? "default" :
                  record.final_action.includes("卖") ? "destructive" : "secondary"
                }
                className="text-[10px] ml-auto"
              >
                {record.final_action}
              </Badge>
            </div>

            <ScoreBar bull={record.bull_score} bear={record.bear_score} />

            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="space-y-1">
                <span className="text-market-up font-medium">多方论据</span>
                {record.bull_arguments.map((a, i) => (
                  <div key={i} className="text-muted-foreground">
                    <span className="font-numeric">[{a.strength.toFixed(1)}]</span> {a.claim}
                  </div>
                ))}
              </div>
              <div className="space-y-1">
                <span className="text-market-down font-medium">空方论据</span>
                {record.bear_arguments.map((a, i) => (
                  <div key={i} className="text-muted-foreground">
                    <span className="font-numeric">[{a.strength.toFixed(1)}]</span> {a.claim}
                  </div>
                ))}
              </div>
            </div>

            {record.verdict && (
              <div className="border-t pt-2 text-xs space-y-1">
                <div className="flex items-center gap-3">
                  <span className="text-muted-foreground">
                    胜率 <span className="font-numeric">{(record.verdict.win_probability * 100).toFixed(0)}%</span>
                  </span>
                  {record.verdict.risk_reward_ratio != null && (
                    <span className="text-muted-foreground">
                      盈亏比 <span className="font-numeric">{record.verdict.risk_reward_ratio.toFixed(1)}</span>
                    </span>
                  )}
                  {record.verdict.stop_loss_pct != null && (
                    <span className="text-muted-foreground">
                      止损 <span className="font-numeric text-market-down">{record.verdict.stop_loss_pct.toFixed(1)}%</span>
                    </span>
                  )}
                </div>
                <p className="text-muted-foreground">{record.verdict.reasoning}</p>
              </div>
            )}
          </div>
        )}

        {mutation.isError && (
          <p className="text-xs text-destructive">分析失败: {mutation.error.message}</p>
        )}
      </CardContent>
    </Card>
  )
}
