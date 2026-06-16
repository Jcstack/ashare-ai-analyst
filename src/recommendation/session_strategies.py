"""Session-specific strategy router for smart stock recommendations.

Applies session-aware filtering and re-ranking on top of base screener output.
Per PRD v28.0 FR-REC010 through FR-REC014.
"""

from __future__ import annotations

import logging
from typing import Any

from src.recommendation.models import StockCandidate
from src.recommendation.screener import StockScreener

logger = logging.getLogger(__name__)


class SessionStrategyRouter:
    """Routes screening through session-specific strategies."""

    def __init__(self, screener: StockScreener) -> None:
        self._screener = screener
        self._handlers = {
            "pre_market": self._pre_market_strategy,
            "early": self._early_strategy,
            "mid": self._mid_strategy,
            "late": self._late_strategy,
            "post_market": self._post_market_strategy,
            "anytime": self._post_market_strategy,
        }

    def screen_for_session(
        self,
        style: str,
        session: str,
        market_data: list[dict] | None = None,
        *,
        blacklist: set[str] | None = None,
        user_config: dict[str, Any] | None = None,
    ) -> list[StockCandidate]:
        """Screen candidates with session-specific strategy applied.

        Args:
            style: Investment style key.
            session: Trading session key (pre_market, early, mid, late, post_market).
            market_data: Optional pre-fetched market data.
            blacklist: User blacklist symbols.
            user_config: Optional user config for session-specific tuning.

        Returns:
            Filtered and re-ranked candidate list.
        """
        candidates = self._screener.screen(style, market_data, blacklist=blacklist)
        if not candidates:
            return candidates

        handler = self._handlers.get(session)
        if handler:
            candidates = handler(candidates, style)
            logger.info(
                "Session '%s' strategy applied: %d candidates for style=%s",
                session,
                len(candidates),
                style,
            )

        return candidates

    @staticmethod
    def _pre_market_strategy(
        candidates: list[StockCandidate], style: str
    ) -> list[StockCandidate]:
        """Pre-market: favor overnight intelligence, global correlation signals.

        Boost stable, low-volatility picks. Penalize high-momentum (no intraday data yet).
        """
        for c in candidates:
            stability = c.factors.get("stability", 0.5)
            # Pre-market rewards stability and penalizes pure momentum plays
            c.factors["session_boost"] = round(stability * 0.3, 4)
            c.score = round(c.score * (1 + c.factors["session_boost"] * 0.1), 4)

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates

    @staticmethod
    def _early_strategy(
        candidates: list[StockCandidate], style: str
    ) -> list[StockCandidate]:
        """Early session (09:30-10:30): gap detection, volume surge, momentum.

        Favor high volume ratio (> 2) and strong opening momentum.
        """
        boosted = []
        for c in candidates:
            volume_ratio = c.factors.get("volume_momentum", 0.5)
            momentum = c.factors.get("price_momentum", 0.5)
            # Early session rewards opening volume surges
            boost = 0.0
            if volume_ratio > 0.6:  # High volume ratio
                boost += 0.15
            if momentum > 0.6:  # Strong momentum
                boost += 0.1
            c.factors["session_boost"] = round(boost, 4)
            c.score = round(c.score * (1 + boost), 4)
            boosted.append(c)

        boosted.sort(key=lambda c: c.score, reverse=True)
        return boosted

    @staticmethod
    def _mid_strategy(
        candidates: list[StockCandidate], style: str
    ) -> list[StockCandidate]:
        """Mid session (10:30-14:00): intraday trend confirmation, sector rotation.

        Favor stocks with confirmed trend (positive change + high turnover).
        """
        for c in candidates:
            trend = c.factors.get("trend", 0.5)
            turnover = c.factors.get("turnover", 0.5)
            sector_mom = c.factors.get("sector_momentum", 0.5)
            # Mid-session rewards confirmed intraday trends
            boost = 0.0
            if trend > 0.5 and turnover > 0.4:
                boost += 0.1
            if sector_mom > 0.6:
                boost += 0.05
            c.factors["session_boost"] = round(boost, 4)
            c.score = round(c.score * (1 + boost), 4)

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates

    @staticmethod
    def _late_strategy(
        candidates: list[StockCandidate], style: str
    ) -> list[StockCandidate]:
        """Late session (14:00-15:00): closing assessment, next-day candidates.

        Favor stocks holding gains with declining volatility (consolidation).
        """
        for c in candidates:
            stability = c.factors.get("stability", 0.5)
            trend = c.factors.get("trend", 0.5)
            # Late session rewards stability (holding gains) over volatility
            boost = 0.0
            if stability > 0.5 and trend > 0.4:
                boost += 0.12
            c.factors["session_boost"] = round(boost, 4)
            c.score = round(c.score * (1 + boost), 4)

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates

    @staticmethod
    def _post_market_strategy(
        candidates: list[StockCandidate], style: str
    ) -> list[StockCandidate]:
        """Post-market (15:00-17:00): today's performance review, tomorrow pre-screen.

        Favor fundamentally strong stocks for next-day consideration.
        """
        for c in candidates:
            pe_score = c.factors.get("pe_score", 0.5)
            pb_score = c.factors.get("pb_score", 0.5)
            # Post-market rewards fundamental quality
            fundamental = (pe_score + pb_score) / 2
            boost = fundamental * 0.1
            c.factors["session_boost"] = round(boost, 4)
            c.score = round(c.score * (1 + boost), 4)

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates
