import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Newspaper, Building2, UserCheck, TrendingUp, TrendingDown, Minus, ExternalLink } from "lucide-react"
import { useResearch } from "@/hooks/useResearch"
import { useNavigate } from "react-router-dom"

interface ResearchPanelProps {
  symbol: string
}

function SentimentBadge({ overall }: { overall: string }) {
  const map: Record<string, { label: string; color: string }> = {
    positive: { label: "正面", color: "var(--color-market-up)" },
    negative: { label: "负面", color: "var(--color-market-down)" },
    neutral: { label: "中性", color: "var(--color-market-flat)" },
    mixed: { label: "混合", color: "#f59e0b" },
  }
  const style = map[overall] ?? map.neutral
  return (
    <Badge className="text-xs" style={{ backgroundColor: style.color, color: "white" }}>
      {style.label}
    </Badge>
  )
}

function SectionSkeleton() {
  return (
    <div className="space-y-2">
      <Skeleton className="h-5 w-32" />
      {Array.from({ length: 3 }).map((_, i) => (
        <Skeleton key={i} className="h-12 w-full rounded-lg" />
      ))}
    </div>
  )
}

export function ResearchPanel({ symbol }: ResearchPanelProps) {
  const navigate = useNavigate()
  const { data, isLoading, error } = useResearch(symbol)

  if (isLoading) {
    return (
      <div className="space-y-4">
        <SectionSkeleton />
        <SectionSkeleton />
        <SectionSkeleton />
      </div>
    )
  }

  if (error || !data) {
    return (
      <Card>
        <CardContent className="py-12 text-center text-muted-foreground">
          {error ? "资讯研报加载失败" : "暂无数据"}
        </CardContent>
      </Card>
    )
  }

  const { news, sentiment, fund_holdings, analyst_ratings } = data

  return (
    <div className="space-y-4">
      {/* Sentiment Overview */}
      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <Newspaper className="h-4 w-4 text-info" />
            舆情分析
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {sentiment ? (
            <>
              <div className="flex items-center gap-3">
                <SentimentBadge overall={sentiment.overall} />
                <span className="text-xs text-muted-foreground">
                  综合评分: <span className="font-numeric">{sentiment.score.toFixed(2)}</span>
                </span>
                <div className="flex items-center gap-2 text-xs text-muted-foreground ml-auto">
                  <span className="flex items-center gap-1">
                    <TrendingUp className="h-3 w-3 text-market-up" />
                    {sentiment.positive_count}
                  </span>
                  <span className="flex items-center gap-1">
                    <Minus className="h-3 w-3 text-market-flat" />
                    {sentiment.neutral_count}
                  </span>
                  <span className="flex items-center gap-1">
                    <TrendingDown className="h-3 w-3 text-market-down" />
                    {sentiment.negative_count}
                  </span>
                </div>
              </div>
              {sentiment.summary && (
                <p className="text-xs text-muted-foreground leading-relaxed">{sentiment.summary}</p>
              )}
            </>
          ) : (
            <p className="text-xs text-muted-foreground">暂无情绪分析</p>
          )}

          {/* News List */}
          {news.length > 0 ? (
            <div className="space-y-1.5 max-h-60 overflow-y-auto">
              {news.slice(0, 10).map((item, i) => (
                <div key={i} className="flex items-start gap-2 text-xs border-b last:border-0 pb-1.5">
                  <span className="text-muted-foreground shrink-0 w-32">{item.datetime}</span>
                  <span className="flex-1 leading-relaxed">{item.title}</span>
                  <span className="text-muted-foreground shrink-0">{item.source}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">暂无近期新闻</p>
          )}
        </CardContent>
      </Card>

      {/* Fund Holdings */}
      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <Building2 className="h-4 w-4 text-accent-primary" />
            机构动向
          </CardTitle>
        </CardHeader>
        <CardContent>
          {fund_holdings.length > 0 ? (
            <div className="space-y-1.5 max-h-60 overflow-y-auto">
              {fund_holdings.slice(0, 10).map((item, i) => (
                <div key={i} className="flex items-center justify-between text-xs border-b last:border-0 pb-1.5">
                  <Badge variant="outline" className="text-[10px] shrink-0 mr-2">
                    {String(item.inst_type ?? "—")}
                  </Badge>
                  <span className="flex-1 truncate">{String(item.inst_name ?? "—")}</span>
                  <span className="font-numeric text-muted-foreground ml-2">
                    {item.shares_held != null ? Number(item.shares_held).toLocaleString() + " 万股" : "—"}
                  </span>
                  <span className="font-numeric text-muted-foreground ml-2 w-16 text-right">
                    {item.pct_of_float != null ? Number(item.pct_of_float).toFixed(2) + "%" : "—"}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">暂无机构持仓数据</p>
          )}
        </CardContent>
      </Card>

      {/* Analyst Ratings */}
      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <UserCheck className="h-4 w-4 text-warning" />
            明星分析师
          </CardTitle>
        </CardHeader>
        <CardContent>
          {analyst_ratings.length > 0 ? (
            <div className="space-y-0 max-h-80 overflow-y-auto">
              {/* Table header */}
              <div className="grid grid-cols-[2rem_1fr_1fr_4rem_4.5rem_6rem] gap-2 text-[10px] text-muted-foreground font-medium pb-1.5 border-b px-1">
                <span>#</span>
                <span>分析师</span>
                <span>机构</span>
                <span className="text-right">行业</span>
                <span className="text-right">年收益</span>
                <span className="text-right">最新荐股</span>
              </div>
              {analyst_ratings.slice(0, 15).map((item, i) => {
                const annualReturn = item["12个月收益率"] ?? item["2024年收益率"]
                const ratingCode = String(item["2024最新个股评级-股票代码"] ?? "")
                const ratingName = String(item.latest_rating ?? "")
                return (
                  <div
                    key={i}
                    className="grid grid-cols-[2rem_1fr_1fr_4rem_4.5rem_6rem] gap-2 items-center text-xs border-b last:border-0 py-1.5 px-1 hover:bg-muted/50 rounded-sm"
                  >
                    <span className="font-numeric text-muted-foreground text-[10px]">
                      {String(item.rank ?? i + 1)}
                    </span>
                    <span className="truncate font-medium">
                      {String(item.analyst ?? "—")}
                    </span>
                    <span className="truncate text-muted-foreground">
                      {String(item.institution ?? "—")}
                    </span>
                    <Badge variant="outline" className="text-[10px] justify-self-end px-1.5 py-0">
                      {String(item.industry ?? "—")}
                    </Badge>
                    <span className={`font-numeric text-right text-[11px] font-medium ${annualReturn != null && Number(annualReturn) > 0 ? "text-market-up" : "text-market-down"}`}>
                      {annualReturn != null ? `${Number(annualReturn).toFixed(1)}%` : "—"}
                    </span>
                    <span className="text-right">
                      {ratingCode && ratingName ? (
                        <button
                          onClick={() => navigate(`/stock/${ratingCode}`)}
                          className="inline-flex items-center gap-0.5 text-[11px] text-info hover:text-info/80 hover:underline transition-colors"
                        >
                          {ratingName}
                          <ExternalLink className="h-2.5 w-2.5 shrink-0" />
                        </button>
                      ) : (
                        <span className="text-muted-foreground text-[11px]">—</span>
                      )}
                    </span>
                  </div>
                )
              })}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">暂无分析师评级数据</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
