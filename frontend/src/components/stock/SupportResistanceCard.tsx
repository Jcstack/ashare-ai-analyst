import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Sparkles } from "lucide-react"
import { formatPrice } from "@/lib/utils"
import { useSRAnalysis } from "@/hooks/useFundFlow"
import type { SupportResistanceLevel } from "@/types/stock"
import type { RealtimeQuote } from "@/types/market"

interface SupportResistanceCardProps {
  levels: SupportResistanceLevel[]
  symbol?: string
  realtimeQuote?: RealtimeQuote | null
}

export function SupportResistanceCard({ levels, symbol, realtimeQuote }: SupportResistanceCardProps) {
  const { data: srAnalysis, isLoading: loadingAI } = useSRAnalysis(symbol ?? "")

  const support = levels.filter((l) => l.type === "support")
  const resistance = levels.filter((l) => l.type === "resistance")

  const currentPrice = realtimeQuote?.price ?? null

  const distancePct = (level: number) => {
    if (!currentPrice || currentPrice === 0) return null
    return ((currentPrice - level) / level) * 100
  }

  return (
    <Card>
      <CardHeader className="py-3">
        <CardTitle className="text-sm">支撑与阻力</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {resistance.length > 0 && (
          <div>
            <p className="text-xs font-medium text-muted-foreground mb-1">阻力位</p>
            <div className="space-y-1">
              {resistance.map((r, i) => {
                const dist = distancePct(r.level)
                return (
                  <div key={i} className="flex items-center justify-between">
                    <Badge variant="destructive" className="text-xs">阻力</Badge>
                    <span className="font-mono tabular-nums text-sm">{formatPrice(r.level)}</span>
                    <span className="text-xs text-muted-foreground">
                      触及 {r.touches} 次
                      {dist != null && (
                        <span className="ml-1 text-market-up">{dist > 0 ? "+" : ""}{dist.toFixed(1)}%</span>
                      )}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        )}
        {support.length > 0 && (
          <div>
            <p className="text-xs font-medium text-muted-foreground mb-1">支撑位</p>
            <div className="space-y-1">
              {support.map((s, i) => {
                const dist = distancePct(s.level)
                return (
                  <div key={i} className="flex items-center justify-between">
                    <Badge className="bg-[#26A69A] text-white text-xs">支撑</Badge>
                    <span className="font-mono tabular-nums text-sm">{formatPrice(s.level)}</span>
                    <span className="text-xs text-muted-foreground">
                      触及 {s.touches} 次
                      {dist != null && (
                        <span className="ml-1 text-market-down">{dist > 0 ? "+" : ""}{dist.toFixed(1)}%</span>
                      )}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        )}
        {levels.length === 0 && (
          <p className="text-sm text-muted-foreground">暂无支撑阻力数据</p>
        )}

        {/* AI Analysis Section */}
        {symbol && (
          <div className="border-t pt-2 mt-2">
            {loadingAI ? (
              <div className="space-y-1.5">
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-3/4" />
              </div>
            ) : srAnalysis && srAnalysis.status === "success" && srAnalysis.summary ? (
              <div className="space-y-1.5">
                <div className="flex items-center gap-1 text-xs text-accent-primary">
                  <Sparkles className="h-3 w-3" />
                  <span className="font-medium">AI 分析</span>
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed">{srAnalysis.summary}</p>
                {srAnalysis.advice && (
                  <p className="text-xs text-foreground/80">{srAnalysis.advice}</p>
                )}
              </div>
            ) : (
              <p className="text-[10px] text-muted-foreground">建议结合量价关系、资金流向综合判断</p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
