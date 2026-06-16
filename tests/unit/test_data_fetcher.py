"""Unit tests for src/data/fetcher.py — StockDataFetcher.

Test cases TC-D002 through TC-D004 per PRD Section 6.2:
  - TC-D002: Fetch daily OHLCV, verify DataFrame with English column names
  - TC-D003: Cache hit avoids network call on second request
  - TC-D004: Network error triggers retries, then raises DataCollectionError

Per PRD Section 6.3 mock strategy:
  - Mock AKShare (external dependency) only
  - Use tmp_path for file I/O (cache)
  - Fixed seed for reproducibility
"""

import pandas as pd
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Column mapping: AKShare returns Chinese column names; fetcher renames them.
# This is the expected mapping per PRD AC-D001-2.
# ---------------------------------------------------------------------------
EXPECTED_ENGLISH_COLUMNS = {"date", "open", "close", "high", "low", "volume", "amount"}

CHINESE_TO_ENGLISH = {
    "日期": "date",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
}


class TestFetchDailyOHLCV:
    """Tests for StockDataFetcher.fetch_daily_ohlcv() — TC-D002."""

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_fetch_daily_ohlcv_returns_dataframe(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        sample_akshare_response,
        sample_stocks_config,
        tmp_path,
    ):
        """TC-D002: Mock ak.stock_zh_a_hist, verify returns DataFrame.

        The returned DataFrame must contain English column names and have
        the expected number of rows matching the mock data.
        """
        mock_load_config.return_value = sample_stocks_config
        mock_ak.stock_zh_a_hist.return_value = sample_akshare_response
        mock_ak.stock_zh_a_hist_tx.side_effect = Exception("Tencent unavailable")
        mock_get_data_dir.return_value = tmp_path / "raw"

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        result = fetcher.fetch_daily_ohlcv(
            symbol="000001",
            start_date="20240102",
            end_date="20240115",
        )

        # Assert: result is a DataFrame with correct shape
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 10  # Matches our mock data
        assert not result.empty

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_fetch_daily_ohlcv_column_rename(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        sample_akshare_response,
        sample_stocks_config,
        tmp_path,
    ):
        """TC-D002: Verify Chinese-to-English column mapping.

        AKShare returns columns like '日期', '开盘', '收盘', etc.
        The fetcher must rename them to 'date', 'open', 'close', etc.
        per PRD AC-D001-2.
        """
        mock_load_config.return_value = sample_stocks_config
        mock_ak.stock_zh_a_hist.return_value = sample_akshare_response
        mock_ak.stock_zh_a_hist_tx.side_effect = Exception("Tencent unavailable")
        mock_get_data_dir.return_value = tmp_path / "raw"

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        result = fetcher.fetch_daily_ohlcv(
            symbol="000001",
            start_date="20240102",
            end_date="20240115",
        )

        # Assert: all expected English columns are present
        result_columns = set(result.columns)
        for col in EXPECTED_ENGLISH_COLUMNS:
            assert col in result_columns, (
                f"Expected column '{col}' not found. "
                f"Got columns: {list(result.columns)}"
            )

        # Assert: no Chinese column names remain
        for cn_col in CHINESE_TO_ENGLISH:
            assert cn_col not in result_columns, (
                f"Chinese column '{cn_col}' should have been renamed"
            )

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_fetch_daily_ohlcv_data_types(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        sample_akshare_response,
        sample_stocks_config,
        tmp_path,
    ):
        """TC-D002: Verify output DataFrame column data types.

        Per PRD AC-D002-6, price columns should be float64 and volume
        columns should be int64 or float64.
        """
        mock_load_config.return_value = sample_stocks_config
        mock_ak.stock_zh_a_hist.return_value = sample_akshare_response
        mock_ak.stock_zh_a_hist_tx.side_effect = Exception("Tencent unavailable")
        mock_get_data_dir.return_value = tmp_path / "raw"

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        result = fetcher.fetch_daily_ohlcv(
            symbol="000001",
            start_date="20240102",
            end_date="20240115",
        )

        # Price columns should be numeric (float64)
        for col in ["open", "close", "high", "low"]:
            if col in result.columns:
                assert pd.api.types.is_float_dtype(
                    result[col]
                ) or pd.api.types.is_numeric_dtype(result[col]), (
                    f"Column '{col}' should be numeric, got {result[col].dtype}"
                )

        # Volume should be numeric
        if "volume" in result.columns:
            assert pd.api.types.is_numeric_dtype(result["volume"]), (
                f"Column 'volume' should be numeric, got {result['volume'].dtype}"
            )


class TestCacheHitNoNetworkCall:
    """Tests for cache mechanism — TC-D003."""

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_cache_hit_no_network_call(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        sample_akshare_response,
        sample_stocks_config,
        tmp_path,
    ):
        """TC-D003: First call fetches and caches; second call reads cache.

        Per PRD AC-D001-3: when cache exists and is not expired, AKShare
        is NOT called on subsequent requests.
        """
        mock_load_config.return_value = sample_stocks_config
        # Use recent dates so the data-level freshness check passes
        from datetime import datetime, timedelta

        recent_dates = pd.date_range(
            end=datetime.now().strftime("%Y-%m-%d"), periods=10, freq="B"
        )
        fresh_response = sample_akshare_response.copy()
        fresh_response["日期"] = recent_dates.strftime("%Y-%m-%d")
        mock_ak.stock_zh_a_hist.return_value = fresh_response
        mock_ak.stock_zh_a_hist_tx.side_effect = Exception("Tencent unavailable")
        cache_dir = tmp_path / "raw"
        mock_get_data_dir.return_value = cache_dir

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()

        today = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")

        # First call: should hit AKShare and cache the result
        result1 = fetcher.fetch_daily_ohlcv(
            symbol="000001",
            start_date=start,
            end_date=today,
        )
        assert mock_ak.stock_zh_a_hist.call_count == 1

        # Second call: should read from cache, NOT call AKShare again
        result2 = fetcher.fetch_daily_ohlcv(
            symbol="000001",
            start_date=start,
            end_date=today,
        )
        assert mock_ak.stock_zh_a_hist.call_count == 1, (
            "AKShare should NOT be called on cache hit; "
            f"was called {mock_ak.stock_zh_a_hist.call_count} times"
        )

        # Verify both results are equivalent
        pd.testing.assert_frame_equal(
            result1.reset_index(drop=True),
            result2.reset_index(drop=True),
        )

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_cache_directory_created(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        sample_akshare_response,
        sample_stocks_config,
        tmp_path,
    ):
        """TC-D003: Cache directory is auto-created if it does not exist."""
        mock_load_config.return_value = sample_stocks_config
        mock_ak.stock_zh_a_hist.return_value = sample_akshare_response
        mock_ak.stock_zh_a_hist_tx.side_effect = Exception("Tencent unavailable")
        cache_dir = tmp_path / "raw"
        mock_get_data_dir.return_value = cache_dir
        assert not cache_dir.exists()

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        fetcher.fetch_daily_ohlcv(
            symbol="000001",
            start_date="20240102",
            end_date="20240115",
        )

        # Cache directory should now exist
        assert cache_dir.exists(), "Cache directory was not created"

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_cache_file_exists_after_fetch(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        sample_akshare_response,
        sample_stocks_config,
        tmp_path,
    ):
        """TC-D003: A cache file (parquet) is written after first fetch."""
        mock_load_config.return_value = sample_stocks_config
        mock_ak.stock_zh_a_hist.return_value = sample_akshare_response
        mock_ak.stock_zh_a_hist_tx.side_effect = Exception("Tencent unavailable")
        cache_dir = tmp_path / "raw"
        mock_get_data_dir.return_value = cache_dir

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        fetcher.fetch_daily_ohlcv(
            symbol="000001",
            start_date="20240102",
            end_date="20240115",
        )

        # At least one parquet file should exist in the cache directory
        cache_files = list(cache_dir.glob("*.parquet"))
        assert len(cache_files) >= 1, (
            f"Expected at least one cache file in {cache_dir}, found: {cache_files}"
        )


class TestNetworkErrorRetry:
    """Tests for network error handling and retry — TC-D004."""

    @patch("src.data.fetcher._HAS_ADATA", False)
    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_network_error_retry(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        sample_stocks_config,
        tmp_path,
    ):
        """TC-D004: AKShare raises ConnectionError, verify 3 retries then raises.

        Per PRD AC-D001-4: when AKShare throws ConnectionError, the fetcher
        should retry up to max_retries (3) times. After all retries are
        exhausted, it raises DataCollectionError (adata also disabled).
        """
        mock_load_config.return_value = sample_stocks_config
        mock_get_data_dir.return_value = tmp_path / "raw"
        mock_ak.stock_zh_a_hist_tx.side_effect = Exception("Tencent unavailable")
        mock_ak.stock_zh_a_hist.side_effect = ConnectionError(
            "Simulated network failure"
        )

        from src.data.fetcher import StockDataFetcher, DataCollectionError

        fetcher = StockDataFetcher()

        with pytest.raises(DataCollectionError):
            fetcher.fetch_daily_ohlcv(
                symbol="000001",
                start_date="20240102",
                end_date="20240115",
            )

        # Verify AKShare was called max_retries times
        expected_calls = sample_stocks_config["request"]["max_retries"]
        actual_calls = mock_ak.stock_zh_a_hist.call_count
        assert actual_calls == expected_calls, (
            f"Expected {expected_calls} retry attempts, got {actual_calls} calls"
        )

    @patch("src.data.fetcher._HAS_ADATA", False)
    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_network_timeout_retry(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        sample_stocks_config,
        tmp_path,
    ):
        """TC-D004: AKShare raises TimeoutError, verify retries then raises."""
        mock_load_config.return_value = sample_stocks_config
        mock_get_data_dir.return_value = tmp_path / "raw"
        mock_ak.stock_zh_a_hist_tx.side_effect = Exception("Tencent unavailable")
        mock_ak.stock_zh_a_hist.side_effect = TimeoutError("Simulated timeout")

        from src.data.fetcher import StockDataFetcher, DataCollectionError

        fetcher = StockDataFetcher()

        with pytest.raises(DataCollectionError):
            fetcher.fetch_daily_ohlcv(
                symbol="600519",
                start_date="20240102",
                end_date="20240115",
            )

        assert (
            mock_ak.stock_zh_a_hist.call_count
            == sample_stocks_config["request"]["max_retries"]
        )

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_network_error_then_success(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        sample_akshare_response,
        sample_stocks_config,
        tmp_path,
    ):
        """TC-D004 edge case: Fails twice, succeeds on third attempt.

        Verifies the retry mechanism recovers when the API becomes
        available before retries are exhausted.
        """
        mock_load_config.return_value = sample_stocks_config
        mock_get_data_dir.return_value = tmp_path / "raw"

        mock_ak.stock_zh_a_hist_tx.side_effect = Exception("Tencent unavailable")
        # Fail twice, then succeed
        mock_ak.stock_zh_a_hist.side_effect = [
            ConnectionError("Fail 1"),
            ConnectionError("Fail 2"),
            sample_akshare_response,
        ]

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        result = fetcher.fetch_daily_ohlcv(
            symbol="000001",
            start_date="20240102",
            end_date="20240115",
        )

        # Should succeed after retries
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 10
        assert mock_ak.stock_zh_a_hist.call_count == 3


class TestFetchAllWatchlist:
    """Tests for StockDataFetcher.fetch_all_watchlist()."""

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_fetch_all_watchlist(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        sample_akshare_response,
        sample_stocks_config,
        tmp_path,
    ):
        """TC-D002: Mock AKShare, verify returns dict with all watchlist symbols.

        When fetching data for all stocks in the watchlist, the result
        should be a dict mapping symbol -> DataFrame, containing an entry
        for each stock in the config.
        """
        mock_load_config.return_value = sample_stocks_config
        mock_ak.stock_zh_a_hist.return_value = sample_akshare_response
        mock_ak.stock_zh_a_hist_tx.side_effect = Exception("Tencent unavailable")
        mock_get_data_dir.return_value = tmp_path / "raw"

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        result = fetcher.fetch_all_watchlist()

        # Assert: result is a dict with one entry per watchlist stock
        assert isinstance(result, dict)
        expected_symbols = {s["symbol"] for s in sample_stocks_config["watchlist"]}
        assert set(result.keys()) == expected_symbols, (
            f"Expected symbols {expected_symbols}, got {set(result.keys())}"
        )

        # Each value should be a non-empty DataFrame
        for symbol, df in result.items():
            assert isinstance(df, pd.DataFrame), (
                f"Value for '{symbol}' should be a DataFrame"
            )
            assert not df.empty, f"DataFrame for '{symbol}' should not be empty"


class TestRequestInterval:
    """Tests for polite request interval — AC-D001-5."""

    @patch("src.data.fetcher.time")
    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_request_interval(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        mock_time,
        sample_akshare_response,
        tmp_path,
    ):
        """AC-D001-5: Verify polite intervals between consecutive requests.

        When fetching data for multiple stocks, time.sleep should be called
        between requests to respect AKShare rate limits.
        """
        config = {
            "watchlist": [
                {"symbol": "000001", "name": "平安银行", "board": "main"},
                {"symbol": "600519", "name": "贵州茅台", "board": "main"},
                {"symbol": "300750", "name": "宁德时代", "board": "chinext"},
            ],
            "data_collection": {
                "daily": {
                    "enabled": True,
                    "start_date": "20240101",
                    "end_date": "",
                    "adjust": "qfq",
                },
            },
            "cache": {
                "enabled": False,
                "directory": "data/raw",
                "ttl_hours": 12,
            },
            "request": {
                "interval_seconds": 0.5,
                "max_retries": 3,
                "retry_delay_seconds": 0,
                "timeout_seconds": 10,
            },
        }
        mock_load_config.return_value = config
        mock_ak.stock_zh_a_hist.return_value = sample_akshare_response
        mock_ak.stock_zh_a_hist_tx.side_effect = Exception("Tencent unavailable")
        mock_get_data_dir.return_value = tmp_path / "raw"

        # Make time.monotonic() return increasing values
        monotonic_counter = [0.0]

        def fake_monotonic():
            monotonic_counter[0] += 0.01
            return monotonic_counter[0]

        mock_time.monotonic.side_effect = fake_monotonic
        mock_time.sleep = MagicMock()

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        fetcher.fetch_all_watchlist()

        # With 3 stocks, there should be at least 2 sleep calls
        # (sleep between consecutive requests in fetch_all_watchlist)
        assert mock_time.sleep.call_count >= 2, (
            f"Expected at least 2 sleep calls between 3 requests, "
            f"got {mock_time.sleep.call_count}"
        )


class TestAdataFallback:
    """Tests for adata fallback when both AKShare sources fail."""

    @patch("src.data.fetcher._HAS_ADATA", True)
    @patch("src.data.fetcher._adata")
    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_fallback_to_adata_on_akshare_failure(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        mock_adata,
        sample_stocks_config,
        tmp_path,
    ):
        """When both Tencent and East Money fail, should fall back to adata."""
        mock_load_config.return_value = sample_stocks_config
        mock_get_data_dir.return_value = tmp_path / "raw"
        mock_ak.stock_zh_a_hist_tx.side_effect = Exception("Tencent unavailable")
        mock_ak.stock_zh_a_hist.side_effect = ConnectionError("EastMoney blocked")

        adata_df = pd.DataFrame(
            {
                "stock_code": ["000001"] * 5,
                "trade_time": pd.date_range("2024-01-02", periods=5)
                .strftime("%Y-%m-%d %H:%M:%S")
                .tolist(),
                "trade_date": pd.date_range("2024-01-02", periods=5)
                .strftime("%Y-%m-%d")
                .tolist(),
                "open": [10.0, 10.1, 10.2, 10.3, 10.4],
                "close": [10.1, 10.2, 10.3, 10.4, 10.5],
                "high": [10.2, 10.3, 10.4, 10.5, 10.6],
                "low": [9.9, 10.0, 10.1, 10.2, 10.3],
                "volume": [100000, 110000, 120000, 130000, 140000],
                "amount": [1e6, 1.1e6, 1.2e6, 1.3e6, 1.4e6],
                "change_pct": [1.0, 1.0, 1.0, 1.0, 1.0],
                "change": [0.1, 0.1, 0.1, 0.1, 0.1],
                "turnover_ratio": [0.5, 0.5, 0.5, 0.5, 0.5],
                "pre_close": [10.0, 10.1, 10.2, 10.3, 10.4],
            }
        )
        mock_adata.stock.market.get_market.return_value = adata_df

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        result = fetcher.fetch_daily_ohlcv(
            symbol="000001",
            start_date="20240102",
            end_date="20240110",
        )

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 5
        assert "close" in result.columns
        assert "date" in result.columns
        mock_adata.stock.market.get_market.assert_called_once()

    @patch("src.data.fetcher._HAS_ADATA", True)
    @patch("src.data.fetcher._adata")
    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_adata_empty_raises_error(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        mock_adata,
        sample_stocks_config,
        tmp_path,
    ):
        """When adata returns empty data, should raise DataCollectionError."""
        mock_load_config.return_value = sample_stocks_config
        mock_get_data_dir.return_value = tmp_path / "raw"
        mock_ak.stock_zh_a_hist_tx.side_effect = Exception("Tencent unavailable")
        mock_ak.stock_zh_a_hist.side_effect = ConnectionError("EastMoney blocked")
        mock_adata.stock.market.get_market.return_value = pd.DataFrame()

        from src.data.fetcher import StockDataFetcher, DataCollectionError

        fetcher = StockDataFetcher()
        with pytest.raises(DataCollectionError, match="adata returned empty"):
            fetcher.fetch_daily_ohlcv(
                symbol="000001",
                start_date="20240102",
                end_date="20240110",
            )

    @patch("src.data.fetcher._HAS_ADATA", False)
    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_adata_not_installed_raises_error(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        sample_stocks_config,
        tmp_path,
    ):
        """When adata is not installed, should raise DataCollectionError."""
        mock_load_config.return_value = sample_stocks_config
        mock_get_data_dir.return_value = tmp_path / "raw"
        mock_ak.stock_zh_a_hist_tx.side_effect = Exception("Tencent unavailable")
        mock_ak.stock_zh_a_hist.side_effect = ConnectionError("EastMoney blocked")

        from src.data.fetcher import StockDataFetcher, DataCollectionError

        fetcher = StockDataFetcher()
        with pytest.raises(DataCollectionError, match="adata is not installed"):
            fetcher.fetch_daily_ohlcv(
                symbol="000001",
                start_date="20240102",
                end_date="20240110",
            )
