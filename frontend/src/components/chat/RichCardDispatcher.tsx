/** Rich card dispatcher — routes card type to the correct renderer. */

import type { RichCard } from "@/types/chat"
import { StockAnalysisCard } from "./cards/StockAnalysisCard"
import { TradeDecisionCard } from "./cards/TradeDecisionCard"
import { ScenarioCard } from "./cards/ScenarioCard"
import { GenericCard } from "./cards/GenericCard"

interface RichCardDispatcherProps {
  card: RichCard
}

const CARD_MAP: Record<
  string,
  React.ComponentType<{ props: Record<string, unknown> }>
> = {
  stock_analysis: StockAnalysisCard,
  trade_decision: TradeDecisionCard,
  scenario: ScenarioCard,
  market_overview: StockAnalysisCard,
  portfolio_summary: StockAnalysisCard,
}

export function RichCardDispatcher({ card }: RichCardDispatcherProps) {
  const Component = CARD_MAP[card.type] ?? GenericCard
  return <Component props={card.props} />
}
