"""Unit tests for market data collection methods in StockDataFetcher.

Tests fetch_fundamental, fetch_index, fetch_northbound, and fetch_margin_data
per PRD FR-D001 AC-D001-2 (data completeness).

Per PRD Section 6.3 mock strategy:
  - Mock AKShare (external dependency) only
  - Use tmp_path for file I/O (cache)
"""

from typing import Any, Callable, TypeVar

import pandas as pd
import pytest
from unittest.mock import patch

T = TypeVar("T")


def _passthrough_em_api_call(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Stand-in for ``em_api_call`` that invokes the wrapped callable directly.

    Used as a ``patch`` ``side_effect`` so the East Money proxy retry wrapper is
    bypassed and the underlying AKShare mock is exercised unchanged.
    """
    return fn(*args, **kwargs)


# ---------------------------------------------------------------------------
# Mock AKShare response fixtures for each data type
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_fundamental_response():
    """Mock ak.stock_individual_info_em() response.

    Returns a DataFrame mimicking the AKShare individual info API output
    with Chinese item names and their values.
    """
    return pd.DataFrame(
        {
            "item": [
                "总市值",
                "流通市值",
                "市盈率(动态)",
                "市净率",
                "营业收入",
                "净利润",
                "总股本",
            ],
            "value": [
                "3000亿",
                "2500亿",
                "25.6",
                "3.2",
                "500亿",
                "100亿",
                "100亿股",
            ],
        }
    )


@pytest.fixture
def sample_index_response():
    """Mock ak.stock_zh_index_daily_em() response with Chinese columns."""
    return pd.DataFrame(
        {
            "日期": pd.date_range(
                end=pd.Timestamp.now().strftime("%Y-%m-%d"), periods=5, freq="B"
            ).strftime("%Y-%m-%d"),
            "开盘": [3000.0, 3010.0, 3005.0, 3020.0, 3015.0],
            "收盘": [3010.0, 3005.0, 3020.0, 3015.0, 3025.0],
            "最高": [3015.0, 3015.0, 3025.0, 3025.0, 3030.0],
            "最低": [2995.0, 3000.0, 3000.0, 3010.0, 3010.0],
            "成交量": [200000000, 210000000, 190000000, 220000000, 215000000],
            "成交额": [5e11, 5.2e11, 4.8e11, 5.5e11, 5.3e11],
        }
    )


@pytest.fixture
def sample_northbound_response():
    """Mock ak.stock_hsgt_hist_em(symbol='北向') response."""
    return pd.DataFrame(
        {
            "日期": pd.date_range(
                end=pd.Timestamp.now().strftime("%Y-%m-%d"), periods=5, freq="B"
            ).strftime("%Y-%m-%d"),
            "当日成交净买额": [50.5, -30.2, 80.1, -10.0, 60.3],
            "当日余额": [469.5, 549.8, 439.9, 530.0, 459.7],
            "历史累计净买额": [18000.0, 17969.8, 18049.9, 18039.9, 18100.2],
        }
    )


@pytest.fixture
def sample_margin_response():
    """Mock ak.macro_china_market_margin_sh() response with Chinese columns."""
    return pd.DataFrame(
        {
            "日期": pd.date_range(
                end=pd.Timestamp.now().strftime("%Y-%m-%d"), periods=5, freq="B"
            ).strftime("%Y-%m-%d"),
            "融资余额": [1.5e12, 1.51e12, 1.49e12, 1.52e12, 1.50e12],
            "融券余额": [3e10, 3.1e10, 2.9e10, 3.2e10, 3.0e10],
            "融资融券余额": [1.53e12, 1.541e12, 1.519e12, 1.552e12, 1.53e12],
        }
    )


# ---------------------------------------------------------------------------
# Tests for fetch_fundamental
# ---------------------------------------------------------------------------


class TestFetchFundamental:
    """Tests for StockDataFetcher.fetch_fundamental()."""

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_fetch_fundamental_returns_dataframe(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        sample_fundamental_response,
        sample_stocks_config,
        tmp_path,
    ):
        """Verify fetch_fundamental returns a DataFrame with renamed columns."""
        mock_load_config.return_value = sample_stocks_config
        mock_ak.stock_individual_info_em.return_value = sample_fundamental_response
        mock_get_data_dir.return_value = tmp_path / "raw"

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        result = fetcher.fetch_fundamental("000001")

        assert isinstance(result, pd.DataFrame)
        assert not result.empty
        mock_ak.stock_individual_info_em.assert_called_once_with(symbol="000001")

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_fetch_fundamental_column_rename(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        sample_fundamental_response,
        sample_stocks_config,
        tmp_path,
    ):
        """Verify columns are renamed from 'item'/'value' to 'metric'/'value'."""
        mock_load_config.return_value = sample_stocks_config
        mock_ak.stock_individual_info_em.return_value = sample_fundamental_response
        mock_get_data_dir.return_value = tmp_path / "raw"

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        result = fetcher.fetch_fundamental("000001")

        assert "metric" in result.columns
        assert "value" in result.columns
        assert "item" not in result.columns

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_fetch_fundamental_filters_configured_metrics(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        sample_fundamental_response,
        tmp_path,
    ):
        """Verify only configured metrics are returned.

        The config specifies metrics: [pe_ttm, pb]. The response contains
        7 items, but only the ones matching pe_ttm and pb should remain.
        """
        config = {
            "watchlist": [],
            "data_collection": {
                "daily": {
                    "enabled": True,
                    "start_date": "20240101",
                    "end_date": "",
                    "adjust": "qfq",
                },
                "fundamental": {
                    "enabled": True,
                    "metrics": ["pe_ttm", "pb"],
                },
                "market": {
                    "enabled": True,
                    "indices": [],
                    "northbound": True,
                    "margin": True,
                },
            },
            "cache": {"enabled": True, "directory": "data/raw", "ttl_hours": 12},
            "request": {
                "interval_seconds": 0,
                "max_retries": 3,
                "retry_delay_seconds": 0,
                "timeout_seconds": 10,
            },
        }
        mock_load_config.return_value = config
        mock_ak.stock_individual_info_em.return_value = sample_fundamental_response
        mock_get_data_dir.return_value = tmp_path / "raw"

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        result = fetcher.fetch_fundamental("000001")

        # Should only have 2 rows: 市盈率(动态) -> pe_ttm, 市净率 -> pb
        assert len(result) == 2
        metric_values = set(result["metric"].tolist())
        assert "市盈率(动态)" in metric_values
        assert "市净率" in metric_values

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_fetch_fundamental_cache_hit(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        sample_fundamental_response,
        sample_stocks_config,
        tmp_path,
    ):
        """Verify cache hit avoids second network call for fundamentals."""
        mock_load_config.return_value = sample_stocks_config
        mock_ak.stock_individual_info_em.return_value = sample_fundamental_response
        mock_get_data_dir.return_value = tmp_path / "raw"

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        fetcher.fetch_fundamental("000001")
        assert mock_ak.stock_individual_info_em.call_count == 1

        fetcher.fetch_fundamental("000001")
        assert mock_ak.stock_individual_info_em.call_count == 1

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_fetch_fundamental_network_error(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        sample_stocks_config,
        tmp_path,
    ):
        """Verify network errors trigger retries and raise DataCollectionError."""
        mock_load_config.return_value = sample_stocks_config
        mock_get_data_dir.return_value = tmp_path / "raw"
        mock_ak.stock_individual_info_em.side_effect = ConnectionError(
            "Simulated failure"
        )

        from src.data.fetcher import DataCollectionError, StockDataFetcher

        fetcher = StockDataFetcher()
        with pytest.raises(DataCollectionError):
            fetcher.fetch_fundamental("000001")

        expected_calls = sample_stocks_config["request"]["max_retries"]
        assert mock_ak.stock_individual_info_em.call_count == expected_calls


# ---------------------------------------------------------------------------
# Tests for fetch_index
# ---------------------------------------------------------------------------


class TestFetchIndex:
    """Tests for StockDataFetcher.fetch_index()."""

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_fetch_index_returns_dataframe(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        sample_index_response,
        sample_stocks_config,
        tmp_path,
    ):
        """Verify fetch_index returns a DataFrame with English columns."""
        mock_load_config.return_value = sample_stocks_config
        mock_ak.stock_zh_index_daily_em.return_value = sample_index_response
        mock_get_data_dir.return_value = tmp_path / "raw"

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        result = fetcher.fetch_index("000001")

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 5
        assert not result.empty

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_fetch_index_column_rename(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        sample_index_response,
        sample_stocks_config,
        tmp_path,
    ):
        """Verify Chinese column names are mapped to English."""
        mock_load_config.return_value = sample_stocks_config
        mock_ak.stock_zh_index_daily_em.return_value = sample_index_response
        mock_get_data_dir.return_value = tmp_path / "raw"

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        result = fetcher.fetch_index("000001")

        expected_cols = {"date", "open", "close", "high", "low", "volume"}
        assert expected_cols.issubset(set(result.columns))

        # No Chinese column names should remain
        for cn_col in ["日期", "开盘", "收盘", "最高", "最低", "成交量"]:
            assert cn_col not in result.columns

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_fetch_index_sse_prefix(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        sample_index_response,
        sample_stocks_config,
        tmp_path,
    ):
        """Verify SSE index gets 'sh' prefix (e.g. 000001 -> sh000001)."""
        mock_load_config.return_value = sample_stocks_config
        mock_ak.stock_zh_index_daily_em.return_value = sample_index_response
        mock_get_data_dir.return_value = tmp_path / "raw"

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        fetcher.fetch_index("000001")

        mock_ak.stock_zh_index_daily_em.assert_called_once_with(symbol="sh000001")

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_fetch_index_szse_prefix(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        sample_index_response,
        sample_stocks_config,
        tmp_path,
    ):
        """Verify SZSE index gets 'sz' prefix (e.g. 399001 -> sz399001)."""
        mock_load_config.return_value = sample_stocks_config
        mock_ak.stock_zh_index_daily_em.return_value = sample_index_response
        mock_get_data_dir.return_value = tmp_path / "raw"

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        fetcher.fetch_index("399001")

        mock_ak.stock_zh_index_daily_em.assert_called_once_with(symbol="sz399001")

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_fetch_index_chinext(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        sample_index_response,
        sample_stocks_config,
        tmp_path,
    ):
        """Verify ChiNext index (399006) gets 'sz' prefix."""
        mock_load_config.return_value = sample_stocks_config
        mock_ak.stock_zh_index_daily_em.return_value = sample_index_response
        mock_get_data_dir.return_value = tmp_path / "raw"

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        fetcher.fetch_index("399006")

        mock_ak.stock_zh_index_daily_em.assert_called_once_with(symbol="sz399006")

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_fetch_index_cache_hit(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        sample_index_response,
        sample_stocks_config,
        tmp_path,
    ):
        """Verify cache hit avoids second network call for index data."""
        mock_load_config.return_value = sample_stocks_config
        mock_ak.stock_zh_index_daily_em.return_value = sample_index_response
        mock_get_data_dir.return_value = tmp_path / "raw"

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        fetcher.fetch_index("000001")
        assert mock_ak.stock_zh_index_daily_em.call_count == 1

        fetcher.fetch_index("000001")
        assert mock_ak.stock_zh_index_daily_em.call_count == 1

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_fetch_index_network_error(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        sample_stocks_config,
        tmp_path,
    ):
        """Verify network errors trigger retries and raise DataCollectionError."""
        mock_load_config.return_value = sample_stocks_config
        mock_get_data_dir.return_value = tmp_path / "raw"
        mock_ak.stock_zh_index_daily_em.side_effect = ConnectionError(
            "Simulated failure"
        )

        from src.data.fetcher import DataCollectionError, StockDataFetcher

        fetcher = StockDataFetcher()
        with pytest.raises(DataCollectionError):
            fetcher.fetch_index("000001")

        expected_calls = sample_stocks_config["request"]["max_retries"]
        assert mock_ak.stock_zh_index_daily_em.call_count == expected_calls


# ---------------------------------------------------------------------------
# Tests for fetch_northbound
# ---------------------------------------------------------------------------


class TestFetchNorthbound:
    """Tests for StockDataFetcher.fetch_northbound()."""

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_fetch_northbound_returns_dataframe(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        sample_northbound_response,
        sample_stocks_config,
        tmp_path,
    ):
        """Verify fetch_northbound returns a DataFrame with mapped columns."""
        mock_load_config.return_value = sample_stocks_config
        mock_ak.stock_hsgt_hist_em.return_value = sample_northbound_response
        mock_get_data_dir.return_value = tmp_path / "raw"

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        result = fetcher.fetch_northbound()

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 5
        assert not result.empty

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_fetch_northbound_column_rename(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        sample_northbound_response,
        sample_stocks_config,
        tmp_path,
    ):
        """Verify columns are renamed to date, net_buy_amount, etc."""
        mock_load_config.return_value = sample_stocks_config
        mock_ak.stock_hsgt_hist_em.return_value = sample_northbound_response
        mock_get_data_dir.return_value = tmp_path / "raw"

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        result = fetcher.fetch_northbound()

        expected_cols = {
            "date",
            "net_buy_amount",
            "daily_quota_balance",
            "cumulative_net_buy",
        }
        assert expected_cols.issubset(set(result.columns))

        # No Chinese column names should remain
        for cn_col in ["日期", "当日成交净买额", "当日余额", "历史累计净买额"]:
            assert cn_col not in result.columns

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_fetch_northbound_api_call(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        sample_northbound_response,
        sample_stocks_config,
        tmp_path,
    ):
        """Verify the correct AKShare API is called with symbol='北向'."""
        mock_load_config.return_value = sample_stocks_config
        mock_ak.stock_hsgt_hist_em.return_value = sample_northbound_response
        mock_get_data_dir.return_value = tmp_path / "raw"

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        fetcher.fetch_northbound()

        mock_ak.stock_hsgt_hist_em.assert_called_once_with(symbol="北向资金")

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_fetch_northbound_cache_hit(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        sample_northbound_response,
        sample_stocks_config,
        tmp_path,
    ):
        """Verify cache hit avoids second network call."""
        mock_load_config.return_value = sample_stocks_config
        mock_ak.stock_hsgt_hist_em.return_value = sample_northbound_response
        mock_get_data_dir.return_value = tmp_path / "raw"

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        fetcher.fetch_northbound()
        assert mock_ak.stock_hsgt_hist_em.call_count == 1

        fetcher.fetch_northbound()
        assert mock_ak.stock_hsgt_hist_em.call_count == 1

    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_fetch_northbound_network_error(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        sample_stocks_config,
        tmp_path,
    ):
        """Verify network errors trigger retries and raise DataCollectionError."""
        mock_load_config.return_value = sample_stocks_config
        mock_get_data_dir.return_value = tmp_path / "raw"
        mock_ak.stock_hsgt_hist_em.side_effect = ConnectionError("Simulated failure")

        from src.data.fetcher import DataCollectionError, StockDataFetcher

        fetcher = StockDataFetcher()
        with pytest.raises(DataCollectionError):
            fetcher.fetch_northbound()

        expected_calls = sample_stocks_config["request"]["max_retries"]
        assert mock_ak.stock_hsgt_hist_em.call_count == expected_calls


# ---------------------------------------------------------------------------
# Tests for fetch_margin_data
# ---------------------------------------------------------------------------


class TestFetchMarginData:
    """Tests for StockDataFetcher.fetch_margin_data()."""

    @patch(
        "src.data.eastmoney_proxy.em_api_call",
        side_effect=_passthrough_em_api_call,
    )
    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_fetch_margin_data_returns_dataframe(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        _mock_em,
        sample_margin_response,
        sample_stocks_config,
        tmp_path,
    ):
        """Verify fetch_margin_data returns a DataFrame."""
        mock_load_config.return_value = sample_stocks_config
        mock_ak.macro_china_market_margin_sh.return_value = sample_margin_response
        mock_ak.macro_china_market_margin_sz.return_value = sample_margin_response
        mock_get_data_dir.return_value = tmp_path / "raw"

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        result = fetcher.fetch_margin_data()

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 5
        assert not result.empty

    @patch(
        "src.data.eastmoney_proxy.em_api_call",
        side_effect=_passthrough_em_api_call,
    )
    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_fetch_margin_data_column_rename(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        _mock_em,
        sample_margin_response,
        sample_stocks_config,
        tmp_path,
    ):
        """Verify columns are renamed to date, margin_balance, short_balance."""
        mock_load_config.return_value = sample_stocks_config
        mock_ak.macro_china_market_margin_sh.return_value = sample_margin_response
        mock_ak.macro_china_market_margin_sz.return_value = sample_margin_response
        mock_get_data_dir.return_value = tmp_path / "raw"

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        result = fetcher.fetch_margin_data()

        expected_cols = {"date", "margin_balance", "short_balance"}
        assert expected_cols.issubset(set(result.columns))

        # No Chinese column names should remain
        for cn_col in ["日期", "融资余额", "融券余额"]:
            assert cn_col not in result.columns

    @patch(
        "src.data.eastmoney_proxy.em_api_call",
        side_effect=_passthrough_em_api_call,
    )
    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_fetch_margin_data_cache_hit(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        _mock_em,
        sample_margin_response,
        sample_stocks_config,
        tmp_path,
    ):
        """Verify cache hit avoids second network call."""
        mock_load_config.return_value = sample_stocks_config
        mock_ak.macro_china_market_margin_sh.return_value = sample_margin_response
        mock_ak.macro_china_market_margin_sz.return_value = sample_margin_response
        mock_get_data_dir.return_value = tmp_path / "raw"

        from src.data.fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        fetcher.fetch_margin_data()
        assert mock_ak.macro_china_market_margin_sh.call_count == 1

        fetcher.fetch_margin_data()
        assert mock_ak.macro_china_market_margin_sh.call_count == 1

    @patch(
        "src.data.eastmoney_proxy.em_api_call",
        side_effect=_passthrough_em_api_call,
    )
    @patch("src.data.fetcher.get_data_dir")
    @patch("src.data.fetcher.load_config")
    @patch("src.data.fetcher.ak")
    def test_fetch_margin_data_network_error(
        self,
        mock_ak,
        mock_load_config,
        mock_get_data_dir,
        _mock_em,
        sample_stocks_config,
        tmp_path,
    ):
        """Verify network errors trigger retries and raise DataCollectionError."""
        mock_load_config.return_value = sample_stocks_config
        mock_get_data_dir.return_value = tmp_path / "raw"
        mock_ak.macro_china_market_margin_sh.side_effect = ConnectionError(
            "Simulated failure"
        )

        from src.data.fetcher import DataCollectionError, StockDataFetcher

        fetcher = StockDataFetcher()
        with pytest.raises(DataCollectionError):
            fetcher.fetch_margin_data()

        expected_calls = sample_stocks_config["request"]["max_retries"]
        assert mock_ak.macro_china_market_margin_sh.call_count == expected_calls
