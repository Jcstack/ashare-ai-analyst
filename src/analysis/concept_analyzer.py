"""Concept board analyzer — heat scoring and stock-concept correlation.

Per PRD v3.3 FR-CS002 / FR-CS003:
* Multi-factor heat scoring for concept boards
* Per-stock concept correlation analysis with resonance detection
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from src.data.concept_board import ConceptBoardService
from src.utils.logger import get_logger

logger = get_logger("analysis.concept_analyzer")

_RANK_CACHE_TTL = 120  # seconds — concept hot ranking endpoint cache


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ConceptHeatItem:
    """A concept board with multi-factor heat score."""

    code: str
    name: str
    pct_change: float = 0.0
    amount: float = 0.0
    up_count: int = 0
    down_count: int = 0
    heat_score: float = 0.0
    leader_symbol: str = ""
    leader_name: str = ""
    leader_pct: float = 0.0


@dataclass
class StockConceptDetail:
    """A concept associated with a stock, enriched with rank info."""

    code: str
    name: str
    pct_change: float = 0.0
    amount: float = 0.0
    up_count: int = 0
    down_count: int = 0
    stock_rank_pct: float | None = None  # percentile within board


@dataclass
class ResonanceInfo:
    """Concept resonance detection result."""

    level: str = "none"  # none | weak | moderate | strong
    concepts: list[str] = field(default_factory=list)
    top_driver: str | None = None
    rank_in_driver: str = ""  # 领涨 | 跟涨 | 滞涨


@dataclass
class StockConceptAnalysis:
    """Full concept analysis for a stock."""

    symbol: str
    industry: str = ""
    concepts: list[StockConceptDetail] = field(default_factory=list)
    resonance: ResonanceInfo = field(default_factory=ResonanceInfo)


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class ConceptAnalyzer:
    """Multi-factor concept heat ranking and stock-concept analysis.

    Args:
        concept_service: Pre-configured ConceptBoardService instance.
    """

    # Heat scoring weights
    W_PCT = 0.4
    W_AMOUNT = 0.3
    W_BREADTH = 0.3

    def __init__(self, concept_service: ConceptBoardService) -> None:
        self._svc = concept_service
        self._rank_cache: tuple[float, list[Any]] | None = None

    # ---- heat ranking -------------------------------------------------------

    def rank_concepts(self, top_n: int = 20) -> list[ConceptHeatItem]:
        """Return concept boards ranked by multi-factor heat score.

        Heat = 0.4 × norm(|pct_change|) + 0.3 × norm(amount) + 0.3 × norm(breadth)

        Results are cached for 120 seconds to avoid redundant AKShare calls.
        """
        if self._rank_cache is not None:
            ts, cached_items = self._rank_cache
            if time.time() - ts < _RANK_CACHE_TTL and len(cached_items) >= top_n:
                return cached_items[:top_n]

        boards = self._svc.fetch_concept_list()
        if not boards:
            return []

        # Compute raw metrics
        abs_pcts = [abs(b.pct_change) for b in boards]
        amounts = [b.amount for b in boards]
        breadths = [b.up_count / max(b.up_count + b.down_count, 1) for b in boards]

        # Min-max normalise
        norm_pct = _min_max_norm(abs_pcts)
        norm_amt = _min_max_norm(amounts)
        norm_brd = _min_max_norm(breadths)

        items: list[ConceptHeatItem] = []
        for i, board in enumerate(boards):
            score = (
                self.W_PCT * norm_pct[i]
                + self.W_AMOUNT * norm_amt[i]
                + self.W_BREADTH * norm_brd[i]
            ) * 100

            items.append(
                ConceptHeatItem(
                    code=board.code,
                    name=board.name,
                    pct_change=board.pct_change,
                    amount=board.amount,
                    up_count=board.up_count,
                    down_count=board.down_count,
                    heat_score=round(score, 1),
                )
            )

        # Sort by heat_score descending
        items.sort(key=lambda x: x.heat_score, reverse=True)

        # Fetch leader stock for top N
        for item in items[:top_n]:
            self._fill_leader(item)

        # Cache the full result for subsequent requests
        self._rank_cache = (time.time(), items[:top_n])
        return items[:top_n]

    def _fill_leader(self, item: ConceptHeatItem) -> None:
        """Fill leader stock info for a heat item."""
        if not item.code or not item.code.startswith("BK"):
            return
        try:
            constituents = self._svc.fetch_concept_constituents(item.code)
            if constituents:
                # Sort by pct_change descending, pick the leader
                valid = [c for c in constituents if c.pct_change is not None]
                if valid:
                    leader = max(valid, key=lambda c: c.pct_change or 0.0)
                    item.leader_symbol = leader.symbol
                    item.leader_name = leader.name
                    item.leader_pct = leader.pct_change or 0.0
        except Exception as exc:
            logger.debug("Failed to fetch leader for %s: %s", item.code, exc)

    # ---- stock concept analysis ---------------------------------------------

    def analyze_stock_concepts(self, symbol: str) -> StockConceptAnalysis:
        """Full concept analysis for a stock: concepts + resonance.

        1. Fetch stock's concepts via ConceptBoardService
        2. Compute rank within each concept's constituents
        3. Detect resonance (multiple concepts moving together)
        4. Identify top driver concept
        """
        sc = self._svc.fetch_stock_concepts(symbol)
        result = StockConceptAnalysis(symbol=symbol, industry=sc.industry)

        if not sc.concepts:
            return result

        # Build concept details with rank
        for ci in sc.concepts:
            detail = StockConceptDetail(
                code=ci.code,
                name=ci.name,
                pct_change=ci.pct_change,
                amount=ci.amount,
                up_count=ci.up_count,
                down_count=ci.down_count,
            )
            # Compute stock rank within this concept
            if ci.code:
                detail.stock_rank_pct = self._compute_rank(symbol, ci.code)
            result.concepts.append(detail)

        # Detect resonance
        result.resonance = self._detect_resonance(symbol, result.concepts)

        return result

    def _compute_rank(self, symbol: str, board_code: str) -> float | None:
        """Compute the stock's percentile rank within a concept board.

        Returns 0.0 (best performer) to 1.0 (worst performer), or None.
        """
        # AKShare requires BK-prefixed codes; numeric codes from CoreConception
        # API (e.g. "1222") will cause "index out of bounds" errors.
        if not board_code.startswith("BK"):
            return None
        try:
            constituents = self._svc.fetch_concept_constituents(board_code)
        except Exception:
            return None

        valid = [c for c in constituents if c.pct_change is not None]
        if not valid:
            return None

        # Sort descending by pct_change
        valid.sort(key=lambda c: c.pct_change or 0.0, reverse=True)
        total = len(valid)
        for idx, c in enumerate(valid):
            if c.symbol == symbol:
                return round(idx / max(total, 1), 2)
        return None

    def _detect_resonance(
        self,
        symbol: str,
        concepts: list[StockConceptDetail],
    ) -> ResonanceInfo:
        """Detect concept resonance for a stock.

        Resonance levels:
          strong  — ≥5 concepts with pct > 1% OR ≥3 with pct > 2%
          moderate — ≥3 concepts with pct > 1%
          weak    — ≥2 concepts with pct > 0.5%
          none    — otherwise
        """
        rising_1 = [c for c in concepts if c.pct_change > 1.0]
        rising_2 = [c for c in concepts if c.pct_change > 2.0]
        rising_half = [c for c in concepts if c.pct_change > 0.5]

        if len(rising_1) >= 5 or len(rising_2) >= 3:
            level = "strong"
            resonance_concepts = [c.name for c in rising_1]
        elif len(rising_1) >= 3:
            level = "moderate"
            resonance_concepts = [c.name for c in rising_1]
        elif len(rising_half) >= 2:
            level = "weak"
            resonance_concepts = [c.name for c in rising_half]
        else:
            return ResonanceInfo()

        # Identify top driver (highest pct_change among resonance concepts)
        top_driver_detail = max(
            (c for c in concepts if c.name in resonance_concepts),
            key=lambda c: c.pct_change,
            default=None,
        )

        top_driver = top_driver_detail.name if top_driver_detail else None
        rank_in_driver = ""
        if top_driver_detail and top_driver_detail.stock_rank_pct is not None:
            pct = top_driver_detail.stock_rank_pct
            if pct <= 0.1:
                rank_in_driver = "领涨"
            elif pct <= 0.7:
                rank_in_driver = "跟涨"
            else:
                rank_in_driver = "滞涨"

        return ResonanceInfo(
            level=level,
            concepts=resonance_concepts,
            top_driver=top_driver,
            rank_in_driver=rank_in_driver,
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _min_max_norm(values: list[float]) -> list[float]:
    """Min-max normalise a list of floats to [0, 1]."""
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    rng = hi - lo
    if rng == 0:
        return [0.5] * len(values)
    return [(v - lo) / rng for v in values]
