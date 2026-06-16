"""Tests for MacroCalendarFetcher and MacroRelease."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pandas as pd

from src.data.macro_calendar import MacroCalendarFetcher, MacroRelease, _safe_float


class TestSafeFloat:
    def test_none(self):
        assert _safe_float(None) is None

    def test_valid_float(self):
        assert _safe_float(3.14159) == 3.14

    def test_valid_string(self):
        assert _safe_float("2.5") == 2.5

    def test_nan(self):
        assert _safe_float(float("nan")) is None

    def test_invalid(self):
        assert _safe_float("abc") is None

    def test_empty_string(self):
        assert _safe_float("") is None


class TestMacroRelease:
    def test_to_dict(self):
        r = MacroRelease(
            indicator="CPI年率",
            country="CN",
            date="2026-01-15",
            actual=2.3,
            forecast=2.1,
            previous=2.0,
            surprise=0.2,
            importance="high",
        )
        d = r.to_dict()
        assert d["indicator"] == "CPI年率"
        assert d["surprise"] == 0.2
        assert d["country"] == "CN"

    def test_to_dict_with_none_values(self):
        r = MacroRelease(
            indicator="PMI",
            country="CN",
            date="2026-02",
            actual=50.1,
            forecast=None,
            previous=None,
            surprise=None,
            importance="high",
        )
        d = r.to_dict()
        assert d["forecast"] is None
        assert d["surprise"] is None


class TestMacroCalendarFetcher:
    def test_cache_hit(self):
        fetcher = MacroCalendarFetcher()
        releases = [MacroRelease("CPI", "CN", "2026-01", 2.0, 1.9, 1.8, 0.1, "high")]
        fetcher._cache["china"] = (time.monotonic(), releases)
        result = fetcher.fetch_china_calendar()
        assert result == releases

    def test_cache_expired(self):
        fetcher = MacroCalendarFetcher()
        releases = [MacroRelease("CPI", "CN", "2026-01", 2.0, 1.9, 1.8, 0.1, "high")]
        fetcher._cache["china"] = (time.monotonic() - 7200, releases)  # 2h ago
        assert fetcher._get_cached("china") is None

    def test_circuit_breaker_open_skips(self):
        fetcher = MacroCalendarFetcher()
        fetcher._circuit._state = "open"
        fetcher._circuit._last_failure_time = time.monotonic()
        result = fetcher.fetch_china_calendar()
        assert result == []

    @patch("src.data.macro_calendar.MacroCalendarFetcher._fetch_indicator")
    def test_fetch_china_populates_cache(self, mock_fetch):
        releases = [
            MacroRelease("CPI年率", "CN", "2026-01", 2.3, 2.1, 2.0, 0.2, "high")
        ]
        mock_fetch.return_value = releases
        fetcher = MacroCalendarFetcher()
        result = fetcher.fetch_china_calendar()
        assert len(result) > 0
        assert "china" in fetcher._cache

    @patch("src.data.macro_calendar.MacroCalendarFetcher._fetch_indicator")
    def test_fetch_us_populates_cache(self, mock_fetch):
        releases = [
            MacroRelease("CPI同比", "US", "2026-01", 3.1, 3.0, 2.9, 0.1, "high")
        ]
        mock_fetch.return_value = releases
        fetcher = MacroCalendarFetcher()
        result = fetcher.fetch_us_calendar()
        assert len(result) > 0
        assert "us" in fetcher._cache

    @patch("src.data.macro_calendar.MacroCalendarFetcher._fetch_indicator")
    def test_fetch_all_detects_surprises(self, mock_fetch):
        def side_effect(func_name, name, country, importance, n_latest=3):
            if "cpi" in func_name:
                return [
                    MacroRelease(
                        name, country, "2026-01", 3.5, 2.0, 2.0, 1.5, importance
                    )
                ]
            return []

        mock_fetch.side_effect = side_effect
        fetcher = MacroCalendarFetcher()
        result = fetcher.fetch_all()
        assert result["total_releases"] > 0
        assert len(result["surprises"]) > 0
        assert result["surprises"][0]["surprise"] == 1.5

    def test_fetch_indicator_format_a(self):
        """Test Format A parsing (今值/预测值/前值)."""
        fetcher = MacroCalendarFetcher()
        df = pd.DataFrame(
            {
                "日期": ["2026-01-15", "2026-02-15"],
                "今值": [2.3, 2.1],
                "预测值": [2.1, 2.0],
                "前值": [2.0, 1.9],
            }
        )
        mock_ak = MagicMock()
        mock_ak.macro_china_cpi_yearly.return_value = df
        with patch.dict("sys.modules", {"akshare": mock_ak}):
            releases = fetcher._fetch_indicator(
                "macro_china_cpi_yearly", "CPI年率", "CN", "high", 2
            )
        assert len(releases) == 2
        # Sorted descending by date: 2026-02-15 first (2.1 - 2.0 = 0.1)
        assert releases[0].surprise == 0.1
        assert releases[1].surprise == 0.2

    def test_fetch_indicator_format_b(self):
        """Test Format B parsing (月份/指数)."""
        fetcher = MacroCalendarFetcher()
        df = pd.DataFrame(
            {
                "月份": ["2026年01月", "2026年02月"],
                "制造业指数": [50.1, 49.8],
            }
        )
        mock_ak = MagicMock()
        mock_ak.macro_china_pmi_yearly.return_value = df
        with patch.dict("sys.modules", {"akshare": mock_ak}):
            releases = fetcher._fetch_indicator(
                "macro_china_pmi_yearly", "PMI", "CN", "high", 2
            )
        assert len(releases) == 2
        assert releases[0].actual == 50.1
        assert releases[0].forecast is None

    def test_fetch_indicator_missing_func(self):
        fetcher = MacroCalendarFetcher()
        mock_ak = MagicMock(spec=[])  # no attributes
        with patch.dict("sys.modules", {"akshare": mock_ak}):
            releases = fetcher._fetch_indicator("nonexistent_func", "Test", "CN", "low")
        assert releases == []

    def test_fetch_lpr(self):
        fetcher = MacroCalendarFetcher()
        df = pd.DataFrame(
            {
                "TRADE_DATE": ["2026-01-20", "2026-02-20"],
                "LPR1Y": [3.45, 3.45],
                "LPR5Y": [4.20, 4.20],
            }
        )
        mock_ak = MagicMock()
        mock_ak.macro_china_lpr.return_value = df
        with patch.dict("sys.modules", {"akshare": mock_ak}):
            releases = fetcher.fetch_lpr()
        assert len(releases) == 4  # 2 dates × 2 rates (1Y + 5Y)
        assert releases[0]["indicator"] in ("LPR 1Y", "LPR 5Y")
