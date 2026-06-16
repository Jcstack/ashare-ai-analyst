import { ConceptAnalysisTab } from "@/components/stock/ConceptAnalysisTab"

interface AIOverviewTabProps {
  symbol: string
  stockName: string
  hasPosition: boolean
}

export function AIOverviewTab({ symbol }: AIOverviewTabProps) {
  return (
    <div className="space-y-4">
      <ConceptAnalysisTab symbol={symbol} />
    </div>
  )
}
