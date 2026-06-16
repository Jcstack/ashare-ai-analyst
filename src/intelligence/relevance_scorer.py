"""Intel relevance scorer — computes how relevant intel items are to portfolio holdings.

Per PRD v34.0 FR-IA002: automatic relevance scoring for intel-to-holding mapping.

Uses keyword matching + impact chain templates + sector correlation to score
relevance without LLM calls. Fast enough for per-item scoring.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.intelligence.impact_chain import ImpactChainEngine
from src.intelligence.position_macro_mapper import STOCK_SECTOR_MAP


@dataclass
class RelevanceScore:
    """Relevance assessment of an intel item to a portfolio holding."""

    intel_id: str
    symbol: str
    relevance: float  # 0-1
    impact_direction: str  # positive | negative | neutral
    impact_magnitude: str  # strong | moderate | weak
    transmission_path: str  # human-readable chain
    urgency: str  # immediate | monitor | background
    match_reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "intel_id": self.intel_id,
            "symbol": self.symbol,
            "relevance": round(self.relevance, 3),
            "impact_direction": self.impact_direction,
            "impact_magnitude": self.impact_magnitude,
            "transmission_path": self.transmission_path,
            "urgency": self.urgency,
            "match_reasons": self.match_reasons,
        }


# Sector keywords for text matching (keys match STOCK_SECTOR_MAP values)
_SECTOR_KEYWORDS: dict[str, list[str]] = {
    "黄金": ["黄金", "gold", "贵金属", "避险", "金矿", "金价"],
    "贵金属": ["贵金属", "稀土", "稀有金属"],
    "石油": ["原油", "石油", "天然气", "油价", "OPEC", "炼化"],
    "银行": ["银行", "利率", "降息", "加息", "信贷", "LPR", "净息差"],
    "航运": ["航运", "海运", "运费", "集装箱", "船舶"],
    "航空": ["航空", "航班", "航线", "旅客", "油价"],
    "新能源": ["新能源", "光伏", "风电", "储能", "锂电", "电池"],
    "消费": ["消费", "白酒", "食品", "零售", "品牌"],
    "军工": ["军工", "国防", "航空航天", "军事"],
    "纺织服装": ["纺织", "出口", "服装", "外贸"],
}


class IntelRelevanceScorer:
    """Scores relevance between intel items and portfolio holdings.

    Uses three scoring dimensions:
    1. Direct mention: intel text contains the stock symbol or name
    2. Sector match: intel keywords match the stock's sector
    3. Impact chain: intel triggers an impact chain that reaches the stock
    """

    def __init__(self) -> None:
        self._chain_engine = ImpactChainEngine()

    def score(
        self,
        intel_item: dict[str, Any],
        symbol: str,
        name: str = "",
    ) -> RelevanceScore:
        """Score relevance of a single intel item to a single holding."""
        intel_id = intel_item.get("item_id", intel_item.get("id", ""))
        title = intel_item.get("title", "")
        summary = intel_item.get("summary", "")
        text = f"{title} {summary}"
        related_symbols = intel_item.get("related_symbols", [])

        relevance = 0.0
        match_reasons: list[str] = []
        direction = "neutral"
        magnitude = "weak"
        path = ""

        # --- Dimension 1: Direct symbol/name mention ---
        if symbol in related_symbols or symbol in text:
            relevance += 0.6
            match_reasons.append(f"直接提及{symbol}")
        elif name and name in text:
            relevance += 0.5
            match_reasons.append(f"提及{name}")

        # --- Dimension 2: Sector keyword match ---
        stock_sector = STOCK_SECTOR_MAP.get(symbol, "")
        if stock_sector:
            sector_kws = _SECTOR_KEYWORDS.get(stock_sector, [])
            matched_kws = [kw for kw in sector_kws if kw in text]
            if matched_kws:
                sector_boost = min(0.3, 0.1 * len(matched_kws))
                relevance += sector_boost
                match_reasons.append(f"板块关键词: {', '.join(matched_kws[:3])}")

        # --- Dimension 3: Impact chain matching ---
        chains = self._chain_engine.build_chains_for_event(text)
        if chains:
            impacts = self._chain_engine.find_stock_impact(symbol, chains)
            if impacts:
                best = impacts[0]
                chain_boost = {"strong": 0.4, "moderate": 0.25, "weak": 0.1}.get(
                    best["magnitude"], 0.1
                )
                relevance += chain_boost
                direction = best["direction"]
                magnitude = best["magnitude"]
                path = f"{best['trigger_event'][:20]}→{best['effect']}→{direction}"
                match_reasons.append(f"影响链: {path}")

        # Clamp relevance
        relevance = min(1.0, relevance)

        # Determine urgency
        if relevance >= 0.7:
            urgency = "immediate"
        elif relevance >= 0.3:
            urgency = "monitor"
        else:
            urgency = "background"

        # Upgrade magnitude based on relevance
        if relevance >= 0.7:
            magnitude = "strong"
        elif relevance >= 0.4:
            magnitude = "moderate" if magnitude == "weak" else magnitude

        return RelevanceScore(
            intel_id=intel_id,
            symbol=symbol,
            relevance=relevance,
            impact_direction=direction,
            impact_magnitude=magnitude,
            transmission_path=path,
            urgency=urgency,
            match_reasons=match_reasons,
        )

    def score_portfolio(
        self,
        intel_item: dict[str, Any],
        positions: list[dict[str, str]],
        min_relevance: float = 0.1,
    ) -> list[RelevanceScore]:
        """Score a single intel item against all portfolio positions.

        Returns only scores above min_relevance, sorted by relevance desc.
        """
        scores = []
        for pos in positions:
            symbol = pos.get("symbol", "")
            name = pos.get("name", "")
            if not symbol:
                continue
            score = self.score(intel_item, symbol, name)
            if score.relevance >= min_relevance:
                scores.append(score)

        scores.sort(key=lambda s: s.relevance, reverse=True)
        return scores

    def batch_score(
        self,
        intel_items: list[dict[str, Any]],
        positions: list[dict[str, str]],
        min_relevance: float = 0.1,
    ) -> dict[str, list[RelevanceScore]]:
        """Score multiple intel items against all positions.

        Returns dict mapping symbol -> list of RelevanceScore, sorted by relevance.
        """
        by_symbol: dict[str, list[RelevanceScore]] = {}

        for item in intel_items:
            for pos in positions:
                symbol = pos.get("symbol", "")
                name = pos.get("name", "")
                if not symbol:
                    continue
                score = self.score(item, symbol, name)
                if score.relevance >= min_relevance:
                    by_symbol.setdefault(symbol, []).append(score)

        # Sort each symbol's scores
        for scores in by_symbol.values():
            scores.sort(key=lambda s: s.relevance, reverse=True)

        return by_symbol
