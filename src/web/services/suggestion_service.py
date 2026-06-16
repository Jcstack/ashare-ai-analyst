"""Personalized quick-start suggestion service.

Generates contextual suggestions based on the user's portfolio, watchlist,
and current market conditions.
"""

from __future__ import annotations

from typing import Any

from src.utils.logger import get_logger

logger = get_logger("web.suggestion_service")


class SuggestionService:
    """Generate personalized quick-start suggestions for the chat welcome screen."""

    def __init__(
        self,
        portfolio_service: Any = None,
        stock_service: Any = None,
        realtime_quote_manager: Any = None,
        concept_analyzer: Any = None,
    ) -> None:
        self._portfolio = portfolio_service
        self._stocks = stock_service
        self._quotes = realtime_quote_manager
        self._concepts = concept_analyzer

    def get_quick_questions(self) -> list[dict[str, str]]:
        """Return a list of personalized suggestion prompts.

        Each item has: icon, label, prompt.
        Falls back to generic suggestions if data sources fail.
        """
        suggestions: list[dict[str, str]] = []

        # 1. Portfolio-based: find weakest holding
        suggestions.extend(self._portfolio_suggestions())

        # 2. Concept-based: hot concept board
        suggestions.extend(self._concept_suggestions())

        # 3. Always include portfolio diagnosis and market overview
        suggestions.append(
            {
                "icon": "portfolio",
                "label": "持仓诊断",
                "prompt": "帮我诊断一下当前持仓组合",
            }
        )
        suggestions.append(
            {
                "icon": "market",
                "label": "盘面研判",
                "prompt": "今天大盘走势如何？有什么需要关注的？",
            }
        )

        # Deduplicate and limit to 4
        seen: set[str] = set()
        unique: list[dict[str, str]] = []
        for s in suggestions:
            if s["label"] not in seen:
                seen.add(s["label"])
                unique.append(s)
            if len(unique) >= 4:
                break

        return unique

    def _portfolio_suggestions(self) -> list[dict[str, str]]:
        """Generate suggestions based on portfolio holdings."""
        if not self._portfolio or not self._quotes:
            return []

        try:
            positions = self._portfolio.get_positions()
            if not positions:
                return []

            # Get symbols with positions
            symbols = []
            for pos in positions:
                sym = None
                if isinstance(pos, dict):
                    sym = pos.get("symbol")
                elif hasattr(pos, "symbol"):
                    sym = pos.symbol
                if sym:
                    symbols.append(sym)

            if not symbols:
                return []

            # Fetch real-time quotes to find biggest loser
            quotes = self._quotes.get_quotes(symbols)
            if not quotes:
                return []

            # Find biggest daily decliner
            worst_sym = None
            worst_pct = 0.0
            worst_name = ""

            for q in quotes if isinstance(quotes, list) else [quotes]:
                if isinstance(q, dict):
                    pct = q.get("pct_change", q.get("涨跌幅", 0)) or 0
                    if pct < worst_pct:
                        worst_pct = pct
                        worst_sym = q.get("symbol", q.get("代码", ""))
                        worst_name = q.get("name", q.get("名称", worst_sym))

            if worst_sym and worst_pct < -1:
                return [
                    {
                        "icon": "trending",
                        "label": f"分析{worst_name}",
                        "prompt": f"我持仓的{worst_name}今天下跌了{abs(worst_pct):.1f}%，帮我分析一下是否需要操作",
                    }
                ]
        except Exception:
            logger.debug("Failed to generate portfolio suggestions", exc_info=True)

        return []

    def _concept_suggestions(self) -> list[dict[str, str]]:
        """Generate suggestions based on hot concept boards."""
        if not self._concepts:
            return []

        try:
            top_concepts = self._concepts.rank_concepts(top_n=3)
            if not top_concepts:
                return []

            # Extract the hottest concept name
            concept_name = None
            if isinstance(top_concepts, list) and len(top_concepts) > 0:
                first = top_concepts[0]
                if isinstance(first, dict):
                    concept_name = first.get("name", first.get("板块名称"))
                elif hasattr(first, "name"):
                    concept_name = first.name

            if concept_name:
                return [
                    {
                        "icon": "fire",
                        "label": f"{concept_name}板块",
                        "prompt": f"{concept_name}板块今天领涨，有什么投资机会？",
                    }
                ]
        except Exception:
            logger.debug("Failed to generate concept suggestions", exc_info=True)

        return []
