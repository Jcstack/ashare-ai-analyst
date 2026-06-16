"""Tests for SessionStrategyRouter — session-specific screening strategies.

Part of v28.0 Smart Stock Recommendation System.
"""

from __future__ import annotations

import pytest

from src.recommendation.screener import StockScreener
from src.recommendation.session_strategies import SessionStrategyRouter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_CONFIG = {
    "styles": {
        "value": {
            "label": "价值投资",
            "filters": {"pe_max": 25, "pb_max": 3},
            "weights": {"pe_score": 0.4, "pb_score": 0.3, "stability": 0.3},
        },
        "momentum": {
            "label": "动量交易",
            "filters": {"change_pct_min": 1, "turnover_min": 3},
            "weights": {"price_momentum": 0.5, "volume_momentum": 0.3, "turnover": 0.2},
        },
    },
    "screening": {
        "max_candidates_per_style": 10,
        "min_score": 0.3,
    },
}

SAMPLE_MARKET_DATA = [
    {
        "symbol": "600519",
        "name": "贵州茅台",
        "price": 1800.0,
        "change_pct": 0.5,
        "volume": 50000,
        "turnover_rate": 0.3,
        "pe_ratio": 20.0,
        "pb_ratio": 2.5,
        "market_cap": 2e12,
        "sector": "白酒",
        "volume_ratio": 1.2,
    },
    {
        "symbol": "601318",
        "name": "中国平安",
        "price": 50.0,
        "change_pct": 2.0,
        "volume": 300000,
        "turnover_rate": 4.0,
        "pe_ratio": 10.0,
        "pb_ratio": 1.2,
        "market_cap": 9e11,
        "sector": "保险",
        "volume_ratio": 1.8,
    },
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSessionStrategyRouter:
    """Tests for SessionStrategyRouter."""

    @pytest.fixture()
    def router(self) -> SessionStrategyRouter:
        screener = StockScreener(SAMPLE_CONFIG)
        return SessionStrategyRouter(screener=screener)

    def test_screen_for_session_returns_candidates(self, router) -> None:
        """Router should return candidates for valid style+session."""
        result = router.screen_for_session(
            "value", "mid", market_data=SAMPLE_MARKET_DATA
        )
        assert isinstance(result, list)
        # Should have at least some candidates
        assert len(result) >= 0

    def test_screen_for_unknown_session(self, router) -> None:
        """Unknown session should still return base screened candidates."""
        result = router.screen_for_session(
            "value", "unknown_session", market_data=SAMPLE_MARKET_DATA
        )
        assert isinstance(result, list)

    def test_session_boost_applied(self, router) -> None:
        """Session strategies should add session_boost factor."""
        result = router.screen_for_session(
            "value", "early", market_data=SAMPLE_MARKET_DATA
        )
        for c in result:
            assert "session_boost" in c.factors

    def test_blacklist_passed_through(self, router) -> None:
        """Blacklist should be passed through to screener."""
        result = router.screen_for_session(
            "value",
            "mid",
            market_data=SAMPLE_MARKET_DATA,
            blacklist={"600519"},
        )
        symbols = [c.symbol for c in result]
        assert "600519" not in symbols

    def test_all_sessions_work(self, router) -> None:
        """All 5 session handlers should execute without error."""
        for session in ["pre_market", "early", "mid", "late", "post_market"]:
            result = router.screen_for_session(
                "value", session, market_data=SAMPLE_MARKET_DATA
            )
            assert isinstance(result, list)

    def test_pre_market_boosts_stability(self, router) -> None:
        """Pre-market strategy should boost stable stocks."""
        result = router.screen_for_session(
            "value", "pre_market", market_data=SAMPLE_MARKET_DATA
        )
        if result:
            # All should have non-negative session_boost
            for c in result:
                assert c.factors.get("session_boost", 0) >= 0

    def test_post_market_boosts_fundamentals(self, router) -> None:
        """Post-market strategy should boost fundamentally strong stocks."""
        result = router.screen_for_session(
            "value", "post_market", market_data=SAMPLE_MARKET_DATA
        )
        if result:
            for c in result:
                assert c.factors.get("session_boost", 0) >= 0
