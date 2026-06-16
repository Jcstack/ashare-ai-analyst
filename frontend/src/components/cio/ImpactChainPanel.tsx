/** Impact chain analysis panel — trace event → sector → stock transmission. */

import { useState } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Loader2, Zap, ArrowRight } from "lucide-react"
import { useImpactChain } from "@/hooks/useIntelligence"
import type { ImpactChainResult } from "@/types/cio-dashboard"

const EXAMPLE_EVENTS = [
  "美联储加息50基点",
  "国际油价暴涨",
  "中美贸易摩擦升级",
  "黄金价格创新高",
  "美元指数大幅走强",
]

function ChainView({ result }: { result: ImpactChainResult }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-muted-foreground">影响板块:</span>
        {result.affected_sectors.map((s) => (
          <Badge key={s} variant="outline" className="text-[10px]">
            {s}
          </Badge>
        ))}
      </div>

      {result.chains.map((chain) => (
        <div key={chain.chain_id} className="border rounded-lg p-3 space-y-2">
          <div className="flex items-center gap-2 text-xs">
            <Zap className="h-3 w-3 text-warning" />
            <span className="font-medium">{chain.trigger_event}</span>
            <Badge variant="secondary" className="text-[10px]">{chain.trigger_type}</Badge>
          </div>

          <div className="space-y-1.5 pl-5">
            {chain.transmission_paths.map((path, i) => (
              <div key={i} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <span>{path.cause}</span>
                <ArrowRight className="h-3 w-3 shrink-0" />
                <span>{path.effect}</span>
                <Badge
                  variant={path.direction === "positive" ? "default" : "destructive"}
                  className="text-[9px] ml-1"
                >
                  {path.direction === "positive" ? "利好" : "利空"} {path.magnitude}
                </Badge>
                {path.affected_sectors.length > 0 && (
                  <span className="text-[10px]">
                    [{path.affected_sectors.join(", ")}]
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

export function ImpactChainPanel() {
  const [eventText, setEventText] = useState("")
  const [result, setResult] = useState<ImpactChainResult | null>(null)
  const mutation = useImpactChain()

  const handleAnalyze = (text?: string) => {
    const input = text ?? eventText
    if (!input.trim()) return
    if (text) setEventText(text)
    mutation.mutate(input.trim(), {
      onSuccess: (data) => setResult(data),
    })
  }

  return (
    <Card>
      <CardContent className="py-4 px-5 space-y-3">
        <div className="flex items-center gap-2">
          <Zap className="h-4 w-4 text-warning" />
          <span className="text-caption font-medium">影响链分析</span>
        </div>

        <div className="flex gap-2">
          <Input
            placeholder="输入宏观事件，如：美联储加息50基点"
            value={eventText}
            onChange={(e) => setEventText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleAnalyze()}
            className="flex-1 h-8 text-xs"
          />
          <Button
            size="sm"
            onClick={() => handleAnalyze()}
            disabled={mutation.isPending || !eventText.trim()}
            className="h-8 text-xs"
          >
            {mutation.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : "分析"}
          </Button>
        </div>

        <div className="flex gap-1.5 flex-wrap">
          {EXAMPLE_EVENTS.map((ev) => (
            <button
              key={ev}
              onClick={() => handleAnalyze(ev)}
              className="text-[10px] px-2 py-0.5 rounded-full border hover:bg-muted transition-colors text-muted-foreground"
            >
              {ev}
            </button>
          ))}
        </div>

        {result && result.chains.length > 0 && <ChainView result={result} />}

        {result && result.chains.length === 0 && (
          <p className="text-xs text-muted-foreground">未匹配到影响链模板</p>
        )}

        {mutation.isError && (
          <p className="text-xs text-destructive">分析失败: {mutation.error.message}</p>
        )}
      </CardContent>
    </Card>
  )
}
