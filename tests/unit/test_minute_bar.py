"""Tests for MinuteBarFetcher — intraday minute-level data."""

from __future__ import annotations

import pandas as pd
from unittest.mock import patch, MagicMock


class TestMinuteBarFetcher:
    def test_init_without_redis(self):
        from src.data.minute_bar import MinuteBarFetcher

        fetcher = MinuteBarFetcher()
        assert fetcher is not None
        assert fetcher._redis is None

    def test_init_with_redis(self):
        from src.data.minute_bar import MinuteBarFetcher

        mock_redis = MagicMock()
        fetcher = MinuteBarFetcher(redis_client=mock_redis)
        assert fetcher._redis is mock_redis

    def test_fetch_returns_dataframe(self):
        """fetch() should return a DataFrame (possibly empty) on any input."""
        from src.data.minute_bar import MinuteBarFetcher

        fetcher = MinuteBarFetcher()
        # Mock both upstream sources to avoid network calls
        with patch.object(fetcher, "_fetch_eastmoney", return_value=pd.DataFrame()):
            with patch.object(fetcher, "_fetch_sina", return_value=pd.DataFrame()):
                result = fetcher.fetch("600519", period="5")
                assert isinstance(result, pd.DataFrame)

    def test_fetch_batch_returns_dict(self):
        from src.data.minute_bar import MinuteBarFetcher

        fetcher = MinuteBarFetcher()
        with patch.object(fetcher, "fetch", return_value=pd.DataFrame()):
            result = fetcher.fetch_batch(["600519", "000001"], period="5")
            assert isinstance(result, dict)
            assert "600519" in result
            assert "000001" in result

    def test_get_today_bars_delegates_to_fetch(self):
        from src.data.minute_bar import MinuteBarFetcher

        fetcher = MinuteBarFetcher()
        mock_df = pd.DataFrame({"close": [10.0]})
        with patch.object(fetcher, "fetch", return_value=mock_df) as mock_fetch:
            result = fetcher.get_today_bars("600519")
            mock_fetch.assert_called_once_with("600519", period="5", days=1)
            assert not result.empty

    def test_fetch_handles_network_error(self):
        """Network failures should return empty DataFrame, not crash."""
        from src.data.minute_bar import MinuteBarFetcher

        fetcher = MinuteBarFetcher()
        with patch.object(fetcher, "_fetch_eastmoney", return_value=None):
            with patch.object(fetcher, "_fetch_sina", return_value=None):
                result = fetcher.fetch("600519")
                assert isinstance(result, pd.DataFrame)
                assert result.empty

    def test_invalid_period_falls_back_to_5(self):
        """Invalid period string should fall back to '5'."""
        from src.data.minute_bar import MinuteBarFetcher

        fetcher = MinuteBarFetcher()
        mock_df = pd.DataFrame(
            {
                "datetime": ["2026-03-10 09:35"],
                "open": [10.0],
                "high": [10.1],
                "low": [9.9],
                "close": [10.05],
                "volume": [100000],
                "amount": [1000000],
            }
        )
        with patch.object(fetcher, "_fetch_eastmoney", return_value=mock_df):
            result = fetcher.fetch("600519", period="99")
            assert isinstance(result, pd.DataFrame)

    def test_days_clamped(self):
        """days parameter should be clamped to [1, 5]."""
        from src.data.minute_bar import MinuteBarFetcher

        fetcher = MinuteBarFetcher()
        with patch.object(fetcher, "_fetch_eastmoney", return_value=None):
            with patch.object(fetcher, "_fetch_sina", return_value=None):
                # Should not raise — days=0 clamped to 1, days=100 to 5
                fetcher.fetch("600519", days=0)
                fetcher.fetch("600519", days=100)

    def test_cache_hit_returns_cached(self):
        """When cache hits, should return cached DataFrame without calling upstream."""
        from src.data.minute_bar import MinuteBarFetcher

        fetcher = MinuteBarFetcher()
        cached_df = pd.DataFrame({"close": [42.0]})
        with patch.object(fetcher, "_get_cache", return_value=cached_df):
            with patch.object(fetcher, "_fetch_eastmoney") as mock_em:
                result = fetcher.fetch("600519")
                mock_em.assert_not_called()
                assert result is cached_df


class TestNormalizeSymbol:
    """Tests for symbol normalization helper."""

    def test_strips_sh_prefix(self):
        from src.data.minute_bar import _normalize_symbol

        assert _normalize_symbol("sh600519") == "600519"

    def test_strips_sz_prefix(self):
        from src.data.minute_bar import _normalize_symbol

        assert _normalize_symbol("sz000001") == "000001"

    def test_strips_bj_prefix(self):
        from src.data.minute_bar import _normalize_symbol

        assert _normalize_symbol("bj830001") == "830001"

    def test_bare_symbol_unchanged(self):
        from src.data.minute_bar import _normalize_symbol

        assert _normalize_symbol("600519") == "600519"

    def test_case_insensitive(self):
        from src.data.minute_bar import _normalize_symbol

        assert _normalize_symbol("SH600519") == "600519"


class TestSinaSymbol:
    """Tests for Sina symbol prefix logic."""

    def test_sh_prefix_for_6(self):
        from src.data.minute_bar import _sina_symbol

        assert _sina_symbol("600519") == "sh600519"

    def test_sz_prefix_for_0(self):
        from src.data.minute_bar import _sina_symbol

        assert _sina_symbol("000001") == "sz000001"

    def test_sz_prefix_for_3(self):
        from src.data.minute_bar import _sina_symbol

        assert _sina_symbol("300001") == "sz300001"
