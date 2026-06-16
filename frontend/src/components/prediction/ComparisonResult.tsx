import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { PredictionResult } from "./PredictionResult"
import type { ComparisonPredictionResult } from "@/types/prediction"

interface ComparisonResultProps {
  result: ComparisonPredictionResult
}

export function ComparisonResult({ result }: ComparisonResultProps) {
  if (result.status === "error") {
    return (
      <Card className="border-destructive">
        <CardContent className="py-6">
          <p className="text-destructive">{result.message ?? "对比分析失败"}</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      {/* Summary */}
      {result.comparison_summary && (
        <Card className="border-l-2 border-l-[var(--accent-primary)]">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">对比摘要</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm">{result.comparison_summary}</p>
            {result.recommendation_order && result.recommendation_order.length > 0 && (
              <div className="flex items-center gap-2 mt-2">
                <span className="text-xs text-muted-foreground">推荐排序:</span>
                {result.recommendation_order.map((sym, i) => (
                  <Badge key={sym} variant="outline" className="text-xs">
                    #{i + 1} {sym}
                  </Badge>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Individual results */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {result.analyses.map((analysis, i) => (
          <PredictionResult key={i} prediction={analysis} />
        ))}
      </div>
    </div>
  )
}
