import { Badge } from "@/components/ui/badge"
import type { MoveAnalysisFactor } from "@/types/agent"

const CATEGORY_LABELS: Record<string, string> = {
  market: "大盘",
  sector: "板块",
  news: "新闻",
  technical: "技术面",
  flow: "资金",
  sentiment: "情绪",
}

const IMPACT_COLORS: Record<string, string> = {
  positive: "var(--color-market-up)",
  negative: "var(--color-market-down)",
  neutral: "var(--color-market-flat)",
}

const IMPACT_LABELS: Record<string, string> = {
  positive: "利好",
  negative: "利空",
  neutral: "中性",
}

interface Props {
  factors: MoveAnalysisFactor[]
}

export function FactorBar({ factors }: Props) {
  const sorted = [...factors].sort((a, b) => b.weight - a.weight)

  return (
    <div className="space-y-2">
      {sorted.map((f, i) => (
        <div key={i} className="flex items-center gap-2">
          <Badge variant="secondary" className="text-[10px] w-12 justify-center shrink-0">
            {CATEGORY_LABELS[f.category] ?? f.category}
          </Badge>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-0.5">
              <div
                className="h-2 rounded-full transition-all"
                style={{
                  width: `${Math.max(f.weight * 100, 4)}%`,
                  backgroundColor: IMPACT_COLORS[f.impact] ?? IMPACT_COLORS.neutral,
                }}
              />
              <span className="text-xs text-muted-foreground font-numeric shrink-0">
                {Math.round(f.weight * 100)}%
              </span>
              <span
                className="text-[10px] shrink-0"
                style={{ color: IMPACT_COLORS[f.impact] ?? IMPACT_COLORS.neutral }}
              >
                {IMPACT_LABELS[f.impact] ?? f.impact}
              </span>
            </div>
            <p className="text-xs text-muted-foreground truncate">{f.description}</p>
          </div>
        </div>
      ))}
    </div>
  )
}
