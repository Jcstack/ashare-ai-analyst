"""Tests for the web-layer RecommendationService.

NOTE: ``src.web.services.recommendation_service`` is restored in the
recommendation WEB-SERVICE phase (it wraps the backend
``screener``/``review_agent``/``rec_store`` core engine). These tests for
``_deduplicate_by_symbol`` (I-034) were originally co-located in
``test_rec_store.py`` on the legacy branch; they are split out here so they
sit next to their subject module. They will pass once that web service is
restored.
"""

from __future__ import annotations


class TestDeduplicateBySymbol:
    """Tests for RecommendationService._deduplicate_by_symbol (I-034)."""

    def test_removes_duplicate_symbols(self) -> None:
        """Same symbol from different styles → keep highest score only."""
        from src.web.services.recommendation_service import RecommendationService

        recs = [
            {"symbol": "600519", "score": 0.95, "style": "value"},
            {"symbol": "000858", "score": 0.90, "style": "value"},
            {"symbol": "600519", "score": 0.80, "style": "growth"},  # dup
            {"symbol": "000333", "score": 0.75, "style": "momentum"},
            {"symbol": "000858", "score": 0.70, "style": "momentum"},  # dup
        ]
        result = RecommendationService._deduplicate_by_symbol(recs)

        symbols = [r["symbol"] for r in result]
        assert symbols == ["600519", "000858", "000333"]
        # Kept highest score for 600519
        assert result[0]["score"] == 0.95
        assert result[1]["score"] == 0.90

    def test_empty_list(self) -> None:
        from src.web.services.recommendation_service import RecommendationService

        assert RecommendationService._deduplicate_by_symbol([]) == []

    def test_no_duplicates(self) -> None:
        from src.web.services.recommendation_service import RecommendationService

        recs = [
            {"symbol": "600519", "score": 0.9},
            {"symbol": "000858", "score": 0.8},
        ]
        result = RecommendationService._deduplicate_by_symbol(recs)
        assert len(result) == 2
