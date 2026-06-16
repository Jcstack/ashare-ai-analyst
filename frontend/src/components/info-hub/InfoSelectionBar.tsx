/** Floating selection bar — appears when items are selected in the info feed. */

import { useState } from "react"
import { X, BrainCircuit } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useChatStore } from "@/stores/chatStore"
import { IntelAnalysisDialog } from "./IntelAnalysisDialog"
import type { AnalysisConfig } from "./IntelAnalysisDialog"
import type { InfoItem } from "@/types/info-hub"
import type { ThreadContext } from "@/types/chat"

interface InfoSelectionBarProps {
  count: number
  max: number
  items: InfoItem[]
  onClear: () => void
}

export function InfoSelectionBar({ count, max, items, onClear }: InfoSelectionBarProps) {
  const [dialogOpen, setDialogOpen] = useState(false)
  const openChatWithContext = useChatStore((s) => s.openChatWithContext)

  const handleAnalyze = (config: AnalysisConfig) => {
    const itemIds = items.map((i) => i.item_id)
    const context: ThreadContext = {
      mode: config.symbol ? "stock" : "market",
      symbol: config.symbol ?? null,
      intel_item_ids: itemIds,
      matched_portfolio_symbols: config.matchedPortfolioSymbols,
    }
    const citations = items.map((item) => ({
      title: item.title,
      source_name: item.source_name,
      item_id: item.item_id,
      url: item.url,
    }))

    // Build natural user message (no template-like markdown tags)
    const single = items.length === 1
    const itemWord = single ? "这条情报" : `这 ${items.length} 条情报`

    // Resolve symbol display name
    let symbolLabel = ""
    if (config.symbol) {
      const name = config.symbolName ?? config.symbol
      symbolLabel = name !== config.symbol ? `${name}(${config.symbol})` : config.symbol
    }

    // Build opening sentence naturally based on angle + symbol
    let opener: string
    const angle = config.angle
    if (config.symbol) {
      if (angle === "风险预警") {
        opener = `从风险角度分析${itemWord}对${symbolLabel}的影响`
      } else if (angle === "板块机会") {
        opener = `分析${itemWord}对${symbolLabel}所在板块的机会`
      } else {
        opener = `分析${itemWord}对${symbolLabel}的影响`
      }
    } else if (angle === "对持仓影响") {
      opener = `分析${itemWord}对我持仓的影响`
    } else if (angle === "风险预警") {
      opener = `从风险角度分析${itemWord}`
    } else if (angle === "板块机会") {
      opener = `从板块机会角度分析${itemWord}`
    } else {
      opener = `帮我综合分析${itemWord}`
    }

    // Append custom prompt as a natural clause
    if (config.customPrompt) {
      opener += `，${config.customPrompt}`
    }

    // List items with bullet points
    const itemLines = items.map((item) => `· [${item.source_name}] ${item.title}`)
    const message = [opener + "：", ...itemLines].join("\n")

    openChatWithContext(context, message)
    useChatStore.getState().setIntelCitations(citations)
    onClear()
    setDialogOpen(false)
  }

  return (
    <>
      <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 rounded-lg border bg-bg-surface px-4 py-2.5 shadow-lg">
        <span className="text-sm text-text-secondary">
          已选 <span className="font-semibold text-text-primary">{count}</span>
          {count >= max && <span className="text-muted-foreground"> (上限)</span>}
          {" "}条情报
        </span>
        <Button size="sm" className="gap-1.5" onClick={() => setDialogOpen(true)}>
          <BrainCircuit className="h-3.5 w-3.5" />
          关联分析
        </Button>
        <Button variant="ghost" size="icon-sm" onClick={onClear}>
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>

      <IntelAnalysisDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        items={items}
        onAnalyze={handleAnalyze}
      />
    </>
  )
}
