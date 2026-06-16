import { useNavigate } from "react-router-dom"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Flame, Plus } from "lucide-react"

/**
 * Popular A-share stocks shown when watchlist is empty.
 * Uses a static curated list to avoid API dependency for first-time users.
 */
const HOT_STOCKS = [
  { symbol: "600519", name: "贵州茅台", board: "main", desc: "白酒龙头" },
  { symbol: "000001", name: "平安银行", board: "main", desc: "银行龙头" },
  { symbol: "300750", name: "宁德时代", board: "chinext", desc: "新能源龙头" },
  { symbol: "601012", name: "隆基绿能", board: "main", desc: "光伏龙头" },
  { symbol: "002594", name: "比亚迪", board: "main", desc: "新能源汽车" },
  { symbol: "000858", name: "五粮液", board: "main", desc: "白酒" },
]

interface HotStockRecommendProps {
  onAddToWatchlist?: (stock: { symbol: string; name: string; board: string }) => void
}

export function HotStockRecommend({ onAddToWatchlist }: HotStockRecommendProps) {
  const navigate = useNavigate()

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-title flex items-center gap-2">
          <Flame className="h-4 w-4 text-warning" />
          热门关注
        </CardTitle>
        <p className="text-xs text-muted-foreground">
          这些股票关注度较高，点击查看 AI 分析
        </p>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {HOT_STOCKS.map((stock) => (
            <div
              key={stock.symbol}
              className="flex items-center justify-between rounded-lg border p-3 hover:bg-muted/50 transition-colors cursor-pointer"
              onClick={() => navigate(`/stock/${stock.symbol}`)}
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium truncate">{stock.name}</span>
                  <Badge variant="secondary" className="text-[10px] shrink-0">{stock.desc}</Badge>
                </div>
                <span className="text-xs text-muted-foreground">{stock.symbol}</span>
              </div>
              {onAddToWatchlist && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 shrink-0"
                  onClick={(e) => {
                    e.stopPropagation()
                    onAddToWatchlist({ symbol: stock.symbol, name: stock.name, board: stock.board })
                  }}
                >
                  <Plus className="h-3.5 w-3.5" />
                </Button>
              )}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
