"""Tests for ReviewAgent — LLM review of stock recommendation candidates.

Part of v28.0 Smart Stock Recommendation System.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.recommendation.models import StockCandidate
from src.recommendation.review_agent import ReviewAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_candidate(
    symbol: str = "600519",
    name: str = "贵州茅台",
    score: float = 0.85,
) -> StockCandidate:
    """Build a StockCandidate for testing."""
    return StockCandidate(
        symbol=symbol,
        name=name,
        price=1800.0,
        change_pct=1.5,
        volume=50000,
        turnover_rate=0.3,
        pe_ratio=20.0,
        pb_ratio=2.5,
        market_cap=2e12,
        sector="白酒",
        score=score,
        factors={"pe_score": 0.8, "momentum": 0.6},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReviewAgentFallback:
    """Tests for ReviewAgent without LLM (fallback mode)."""

    @pytest.fixture()
    def agent(self) -> ReviewAgent:
        return ReviewAgent(llm_router=None)

    def test_fallback_generates_recommendations(self, agent: ReviewAgent) -> None:
        """Without LLM, should generate fallback recommendations."""
        candidates = [
            _make_candidate(symbol="600519", score=0.85),
            _make_candidate(symbol="000858", name="五粮液", score=0.7),
        ]
        recs = agent.review_candidates(candidates, "value", "mid")
        assert len(recs) == 2
        assert recs[0].symbol == "600519"
        assert recs[0].style == "value"
        assert recs[0].session == "mid"
        assert recs[0].action == "buy"
        assert "多因子筛选" in recs[0].reason
        assert recs[0].ai_analyzed is False

    def test_fallback_filters_low_score(self, agent: ReviewAgent) -> None:
        """Fallback keeps watch-grade candidates (score >= WATCH_SCORE_THRESHOLD).

        The no-LLM fallback uses the more lenient WATCH threshold (0.55), not the
        BUY threshold (0.65) — exercise the exact boundary so the two stay distinct.
        """
        from src.recommendation.review_agent import WATCH_SCORE_THRESHOLD

        candidates = [
            _make_candidate(score=0.85),
            _make_candidate(
                symbol="600000", name="边界股", score=WATCH_SCORE_THRESHOLD
            ),
            _make_candidate(symbol="000001", name="低分股", score=0.54),
        ]
        recs = agent.review_candidates(candidates, "value", "mid")
        kept = {r.symbol for r in recs}
        # 0.55 (== WATCH) kept, 0.54 (< WATCH) dropped.
        assert kept == {"600519", "600000"}
        assert "000001" not in kept

    def test_empty_candidates(self, agent: ReviewAgent) -> None:
        """Empty candidates returns empty list."""
        recs = agent.review_candidates([], "value", "mid")
        assert recs == []

    def test_recommendation_fields(self, agent: ReviewAgent) -> None:
        """Recommendations should have all required fields including confidence and entry_price."""
        candidates = [_make_candidate()]
        recs = agent.review_candidates(candidates, "value", "mid")
        rec = recs[0]
        assert rec.id  # UUID
        assert rec.symbol == "600519"
        assert rec.name == "贵州茅台"
        assert rec.created_at  # ISO timestamp
        assert rec.status == "active"
        assert rec.factors == {"pe_score": 0.8, "momentum": 0.6}
        assert rec.confidence in ("high", "medium", "low")
        assert rec.entry_price == 1800.0  # from candidate price
        assert rec.ai_analyzed is False


class TestReviewAgentWithLLM:
    """Tests for ReviewAgent with mocked LLM."""

    @pytest.fixture()
    def mock_router(self) -> MagicMock:
        router = MagicMock()
        response = MagicMock()
        response.text = json.dumps(
            [
                {
                    "symbol": "600519",
                    "final_score": 0.88,
                    "confidence": "high",
                    "reason": "低估值蓝筹，安全边际充足",
                    "risk_notes": "白酒行业政策风险",
                    "entry_price": 1780.0,
                    "target_price": 2000.0,
                    "stop_loss": 1700.0,
                },
                {
                    "symbol": "000858",
                    "final_score": 0.72,
                    "confidence": "medium",
                    "reason": "估值合理，跟涨龙头",
                    "risk_notes": "跟随风险",
                    "entry_price": None,
                    "target_price": None,
                    "stop_loss": None,
                },
                {
                    "symbol": "000001",
                    "final_score": 0.50,  # below 0.65 threshold
                    "confidence": "low",
                    "reason": "不推荐",
                    "risk_notes": "评分不足",
                    "entry_price": None,
                    "target_price": None,
                    "stop_loss": None,
                },
            ]
        )
        response.model = "test-model"
        router.complete.return_value = response
        return router

    @pytest.fixture()
    def agent(self, mock_router: MagicMock) -> ReviewAgent:
        return ReviewAgent(llm_router=mock_router)

    def test_llm_review(self, agent: ReviewAgent) -> None:
        """LLM review should parse JSON and filter by score."""
        candidates = [
            _make_candidate(symbol="600519", score=0.85),
            _make_candidate(symbol="000858", name="五粮液", score=0.7),
            _make_candidate(symbol="000001", name="平安银行", score=0.6),
        ]
        recs = agent.review_candidates(candidates, "value", "mid")
        # 000001 has final_score=0.50 < 0.65, should be filtered
        assert len(recs) == 2
        assert recs[0].symbol == "600519"
        assert recs[0].score == 0.88
        assert recs[0].confidence == "high"
        assert recs[0].reason == "低估值蓝筹，安全边际充足"
        assert recs[0].entry_price == 1780.0
        assert recs[0].target_price == 2000.0
        assert recs[0].ai_analyzed is True

    def test_llm_with_markdown_response(self, mock_router: MagicMock) -> None:
        """LLM response wrapped in markdown code blocks should parse correctly."""
        mock_router.complete.return_value.text = (
            "```json\n"
            + json.dumps(
                [
                    {
                        "symbol": "600519",
                        "final_score": 0.9,
                        "reason": "强推",
                        "risk_notes": "无",
                        "target_price": None,
                        "stop_loss": None,
                    }
                ]
            )
            + "\n```"
        )
        agent = ReviewAgent(llm_router=mock_router)
        candidates = [_make_candidate()]
        recs = agent.review_candidates(candidates, "value", "mid")
        assert len(recs) == 1
        assert recs[0].score == 0.9

    def test_llm_invalid_json_falls_back(self, mock_router: MagicMock) -> None:
        """Invalid LLM JSON should trigger fallback."""
        mock_router.complete.return_value.text = "not json at all"
        agent = ReviewAgent(llm_router=mock_router)
        candidates = [_make_candidate(score=0.85)]
        recs = agent.review_candidates(candidates, "value", "mid")
        # Should fallback to auto-generated
        assert len(recs) == 1
        assert "多因子筛选" in recs[0].reason
        assert recs[0].ai_analyzed is False

    def test_batching(self, mock_router: MagicMock) -> None:
        """Candidates should be processed in batches of 5."""
        mock_router.complete.return_value.text = json.dumps([])
        agent = ReviewAgent(llm_router=mock_router)
        candidates = [_make_candidate(symbol=f"60{i:04d}") for i in range(12)]
        agent.review_candidates(candidates, "value", "mid")
        # 12 candidates / 5 per batch = 3 batches
        assert mock_router.complete.call_count == 3
