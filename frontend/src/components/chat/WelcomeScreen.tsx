/** Welcome screen — shown when no thread is active.
 * Fetches personalized suggestions from the backend. */

import { useEffect, useState } from "react"
import {
  BrainCircuit,
  TrendingUp,
  Briefcase,
  MessageSquare,
  Flame,
  BarChart3,
} from "lucide-react"
import type { QuickQuestion } from "@/api/chat"
import { getQuickSuggestions } from "@/api/chat"

interface WelcomeScreenProps {
  onSend: (message: string) => void
}

const ICON_MAP: Record<string, typeof TrendingUp> = {
  trending: TrendingUp,
  portfolio: Briefcase,
  market: BarChart3,
  fire: Flame,
  default: MessageSquare,
}

const FALLBACK_SUGGESTIONS: QuickQuestion[] = [
  { icon: "trending", label: "分析个股", prompt: "帮我分析一下贵州茅台" },
  { icon: "portfolio", label: "持仓诊断", prompt: "帮我看看我的持仓情况" },
  { icon: "market", label: "市场概览", prompt: "今天大盘行情怎么样？" },
]

export function WelcomeScreen({ onSend }: WelcomeScreenProps) {
  const [suggestions, setSuggestions] = useState<QuickQuestion[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    getQuickSuggestions()
      .then((data) => {
        if (cancelled) return
        // Filter out items with empty label/prompt to prevent blank blocks
        const valid = (data || []).filter((s) => s.label && s.prompt)
        setSuggestions(valid.length >= 2 ? valid : FALLBACK_SUGGESTIONS)
      })
      .catch(() => {
        if (!cancelled) setSuggestions(FALLBACK_SUGGESTIONS)
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  return (
    <div className="flex flex-1 flex-col items-center justify-center px-4 py-12">
      <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-accent-primary/10 text-accent-primary mb-4">
        <BrainCircuit className="h-6 w-6" />
      </div>
      <h2 className="text-lg font-semibold mb-1">投研 Agent</h2>
      <p className="text-sm text-muted-foreground mb-8 text-center max-w-md">
        你的 AI 投研助手。我会主动获取数据、分析行情、诊断持仓，给出可操作的建议。
      </p>

      <div className="grid gap-3 w-full max-w-sm">
        {loading ? (
          <>
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-16 rounded-md border bg-bg-surface animate-pulse"
              />
            ))}
          </>
        ) : (
          suggestions.map((item) => {
            const Icon = ICON_MAP[item.icon] || ICON_MAP.default
            return (
              <button
                key={item.label}
                className="flex items-center gap-3 rounded-md border bg-bg-surface px-4 py-3 text-left text-sm hover:bg-bg-hover transition-colors"
                onClick={() => onSend(item.prompt)}
              >
                <Icon className="h-4 w-4 text-muted-foreground shrink-0" />
                <div>
                  <div className="font-medium">{item.label}</div>
                  <div className="text-muted-foreground text-xs">{item.prompt}</div>
                </div>
              </button>
            )
          })
        )}
      </div>

      <p className="mt-8 text-[11px] text-muted-foreground text-center max-w-xs">
        AI 分析仅供研究学习参考，不构成任何投资建议。股市有风险，投资需谨慎。
      </p>
    </div>
  )
}
