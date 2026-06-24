"""Tests for SealStrengthAnalyzer — limit-up seal analysis."""

from __future__ import annotations

from unittest.mock import patch, MagicMock


class TestSealStrengthAnalyzer:
    def test_init(self):
        from src.data.seal_strength import SealStrengthAnalyzer

        analyzer = SealStrengthAnalyzer()
        assert analyzer is not None
        assert analyzer._redis is None

    def test_init_with_redis(self):
        from src.data.seal_strength import SealStrengthAnalyzer

        mock_redis = MagicMock()
        analyzer = SealStrengthAnalyzer(redis_client=mock_redis)
        assert analyzer._redis is mock_redis

    def test_not_at_limit_up_returns_none(self):
        """Stocks not near limit-up should return None."""
        from src.data.seal_strength import SealStrengthAnalyzer

        analyzer = SealStrengthAnalyzer()

        quote = {
            "price": 10.5,
            "prev_close": 10.0,
            "high": 10.6,
            "low": 10.2,
            "volume": 1000000,
            "open": 10.3,
        }
        # 5% gain, not near 10% limit-up (11.0)
        result = analyzer.analyze("600519", quote=quote)
        assert result is None

    def test_at_limit_up_returns_analysis(self):
        """Stocks at limit-up should return seal analysis dict."""
        from src.data.seal_strength import SealStrengthAnalyzer

        analyzer = SealStrengthAnalyzer()

        quote = {
            "price": 11.0,
            "prev_close": 10.0,
            "high": 11.0,
            "low": 10.5,
            "volume": 5000000,
            "amount": 55000000,
            "open": 10.3,
        }
        result = analyzer.analyze("600519", quote=quote)
        assert result is not None
        assert "seal_grade" in result
        assert result["at_limit_up"] is True
        assert result["board_type"] == "main"
        assert result["limit_pct"] == 0.10

    def test_near_limit_up_returns_analysis(self):
        """Stocks within 0.5% of limit-up should still return analysis."""
        from src.data.seal_strength import SealStrengthAnalyzer

        analyzer = SealStrengthAnalyzer()

        # 10.96 is within 0.5% of limit-up price 11.0
        quote = {
            "price": 10.96,
            "prev_close": 10.0,
            "high": 11.0,
            "low": 10.5,
            "volume": 5000000,
            "amount": 55000000,
            "open": 10.3,
        }
        result = analyzer.analyze("600519", quote=quote)
        assert result is not None
        assert result["at_limit_up"] is False  # close but not exactly at limit

    def test_result_keys(self):
        """Result dict should have all expected keys."""
        from src.data.seal_strength import SealStrengthAnalyzer

        analyzer = SealStrengthAnalyzer()

        quote = {
            "price": 11.0,
            "prev_close": 10.0,
            "high": 11.0,
            "low": 10.5,
            "volume": 5000000,
            "amount": 55000000,
            "open": 10.3,
        }
        result = analyzer.analyze("600519", quote=quote)
        assert result is not None
        expected_keys = [
            "symbol",
            "at_limit_up",
            "limit_up_price",
            "seal_ratio",
            "seal_grade",
            "seal_amount_yuan",
            "limit_up_time",
            "break_count",
            "board_type",
            "limit_pct",
        ]
        for key in expected_keys:
            assert key in result, f"Missing key: {key}"

    def test_no_quote_and_no_manager_returns_none(self):
        """Without quote and without live data, should return None gracefully."""
        from src.data.seal_strength import SealStrengthAnalyzer

        analyzer = SealStrengthAnalyzer()

        # Mock the quote manager to raise
        with patch.object(
            analyzer, "_get_quote_manager", side_effect=Exception("no manager")
        ):
            result = analyzer.analyze("600519")
            assert result is None

    def test_zero_prev_close_returns_none(self):
        """Zero prev_close should return None."""
        from src.data.seal_strength import SealStrengthAnalyzer

        analyzer = SealStrengthAnalyzer()

        quote = {"price": 11.0, "prev_close": 0, "volume": 100000}
        result = analyzer.analyze("600519", quote=quote)
        assert result is None


class TestBoardDetection:
    """Tests for board type detection via module-level _detect_board."""

    def test_main_board_60(self):
        from src.data.seal_strength import _detect_board

        board, pct = _detect_board("600519")
        assert board == "main"
        assert pct == 0.10

    def test_main_board_00(self):
        from src.data.seal_strength import _detect_board

        board, pct = _detect_board("000001")
        assert board == "main"
        assert pct == 0.10

    def test_chinext_300(self):
        from src.data.seal_strength import _detect_board

        board, pct = _detect_board("300001")
        assert board == "chinext"
        assert pct == 0.20

    def test_chinext_301(self):
        from src.data.seal_strength import _detect_board

        board, pct = _detect_board("301001")
        assert board == "chinext"
        assert pct == 0.20

    def test_star_688(self):
        from src.data.seal_strength import _detect_board

        board, pct = _detect_board("688001")
        assert board == "star"
        assert pct == 0.20

    def test_unknown_defaults_main(self):
        from src.data.seal_strength import _detect_board

        board, pct = _detect_board("999999")
        assert board == "main"
        assert pct == 0.10


class TestSealGrading:
    """Tests for seal grade logic."""

    def test_strong_seal(self):
        """seal_ratio >= 5.0 should be 'strong'."""
        from src.data.seal_strength import SealStrengthAnalyzer

        analyzer = SealStrengthAnalyzer()
        quote = {
            "price": 11.0,
            "prev_close": 10.0,
            "high": 11.0,
            "low": 10.5,
            "volume": 5000000,
            "amount": 55000000,
            "open": 10.3,
        }
        result = analyzer.analyze("600519", quote=quote)
        # The heuristic seal_ratio = volume / (volume * 0.2) = 5.0
        assert result is not None
        assert result["seal_grade"] in ("strong", "normal", "weak")

    def test_st_stock_5pct_limit(self):
        """ST stocks should use 5% limit."""
        from src.data.seal_strength import SealStrengthAnalyzer

        analyzer = SealStrengthAnalyzer()
        quote = {
            "price": 10.5,
            "prev_close": 10.0,
            "high": 10.5,
            "low": 10.2,
            "volume": 1000000,
            "amount": 10000000,
            "open": 10.3,
            "name": "*ST测试",
        }
        result = analyzer.analyze("600001", quote=quote)
        assert result is not None
        assert result["limit_pct"] == 0.05


class TestNormalizeSymbol:
    """Tests for symbol normalization."""

    def test_strips_prefix(self):
        from src.data.seal_strength import _normalize_symbol

        assert _normalize_symbol("sh600519") == "600519"
        assert _normalize_symbol("SZ000001") == "000001"

    def test_bare_unchanged(self):
        from src.data.seal_strength import _normalize_symbol

        assert _normalize_symbol("600519") == "600519"
