import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { ExternalLink } from "lucide-react"
import { useStockNews } from "@/hooks/useNews"
import { SENTIMENT_COLORS } from "@/lib/constants"

interface NewsPanelProps {
  symbol: string
}

const sentimentLabels: Record<string, string> = {
  positive: "利好",
  negative: "利空",
  neutral: "中性",
}

export function NewsPanel({ symbol }: NewsPanelProps) {
  const { data: news, isLoading } = useStockNews(symbol)

  if (isLoading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="space-y-1">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-3 w-2/3" />
          </div>
        ))}
      </div>
    )
  }

  if (!news || news.length === 0) {
    return <p className="text-sm text-muted-foreground py-4 text-center">暂无相关新闻</p>
  }

  return (
    <div className="space-y-2">
      {news.map((item, i) => (
        <Card key={i} className="overflow-hidden">
          <CardContent className="p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  {item.sentiment && (
                    <Badge
                      variant="outline"
                      className="text-[10px] px-1 py-0"
                      style={{
                        color: SENTIMENT_COLORS[item.sentiment] || SENTIMENT_COLORS.neutral,
                        borderColor: SENTIMENT_COLORS[item.sentiment] || SENTIMENT_COLORS.neutral,
                      }}
                    >
                      {sentimentLabels[item.sentiment] || item.sentiment}
                    </Badge>
                  )}
                  <span className="text-xs text-muted-foreground">{item.source}</span>
                  <span className="text-xs text-muted-foreground">{item.datetime}</span>
                </div>
                <p className="text-sm font-medium leading-snug">{item.title}</p>
                {item.content && (
                  <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{item.content}</p>
                )}
              </div>
              {item.url && (
                <a href={item.url} target="_blank" rel="noopener noreferrer" className="shrink-0 text-muted-foreground hover:text-foreground">
                  <ExternalLink className="h-4 w-4" />
                </a>
              )}
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
