"""Real AKShare API integration tests — NO mocks, real network calls.

Every test hits a live Chinese financial data endpoint via AKShare.
All tests are skipped when the China financial network is unreachable
(determined by the ``requires_china_network`` marker).

Rate-limiting is enforced via ``rate_guard.wait()`` before each call,
and ``_bypass_proxy`` ensures direct connections bypass any local proxy.
"""

from __future__ import annotations

import traceback

import pandas as pd
import pytest

from src.data.fetcher import _bypass_proxy
from tests.integration_real.conftest import (
    TestResult,
    measure_time,
    requires_china_network,
)

pytestmark = [pytest.mark.integration_real, requires_china_network]


# ---------------------------------------------------------------------------
# Tencent source
# ---------------------------------------------------------------------------


class TestAKShareTencent:
    """Primary OHLCV source -- Tencent via AKShare."""

    def test_tencent_ohlcv_600519(self, rate_guard, result_collector):
        """Fetch Moutai daily OHLCV from Tencent source."""
        import akshare as ak

        rate_guard.wait()
        try:
            with _bypass_proxy(), measure_time() as timing:
                df = ak.stock_zh_a_hist_tx(
                    symbol="sh600519",
                    start_date="20250101",
                    end_date="20250201",
                )
            assert not df.empty
            assert len(df) > 5
            result_collector.record(
                TestResult(
                    test_name="akshare_tencent_ohlcv_600519",
                    category="data_source",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={"rows": len(df), "columns": list(df.columns)},
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name="akshare_tencent_ohlcv_600519",
                    category="data_source",
                    status="fail",
                    error=f"{type(exc).__name__}: {exc}",
                    details={"traceback": traceback.format_exc()},
                )
            )
            pytest.fail(f"Tencent OHLCV 600519 failed: {exc}")


# ---------------------------------------------------------------------------
# EastMoney source
# ---------------------------------------------------------------------------


class TestAKShareEastMoney:
    """EastMoney data endpoints."""

    def test_eastmoney_ohlcv_000001(self, rate_guard, result_collector):
        """Fetch Ping An Bank daily OHLCV (qfq adjusted)."""
        import akshare as ak

        rate_guard.wait()
        try:
            with _bypass_proxy(), measure_time() as timing:
                df = ak.stock_zh_a_hist(
                    symbol="000001",
                    period="daily",
                    start_date="20250101",
                    end_date="20250201",
                    adjust="qfq",
                )
            assert not df.empty
            result_collector.record(
                TestResult(
                    test_name="akshare_eastmoney_ohlcv_000001",
                    category="data_source",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={"rows": len(df), "columns": list(df.columns)},
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name="akshare_eastmoney_ohlcv_000001",
                    category="data_source",
                    status="fail",
                    error=f"{type(exc).__name__}: {exc}",
                    details={"traceback": traceback.format_exc()},
                )
            )
            pytest.fail(f"EastMoney OHLCV 000001 failed: {exc}")

    def test_fundamental_000001(self, rate_guard, result_collector):
        """Fetch individual stock info for Ping An Bank."""
        import akshare as ak

        rate_guard.wait()
        try:
            with _bypass_proxy(), measure_time() as timing:
                df = ak.stock_individual_info_em(symbol="000001")
            assert not df.empty
            result_collector.record(
                TestResult(
                    test_name="akshare_eastmoney_fundamental_000001",
                    category="data_source",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={"rows": len(df), "columns": list(df.columns)},
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name="akshare_eastmoney_fundamental_000001",
                    category="data_source",
                    status="fail",
                    error=f"{type(exc).__name__}: {exc}",
                    details={"traceback": traceback.format_exc()},
                )
            )
            pytest.fail(f"Fundamental 000001 failed: {exc}")

    def test_index_shanghai(self, rate_guard, result_collector):
        """Fetch Shanghai Composite Index daily data."""
        import akshare as ak

        rate_guard.wait()
        try:
            with _bypass_proxy(), measure_time() as timing:
                df = ak.stock_zh_index_daily_em(
                    symbol="sh000001",
                    start_date="20250101",
                    end_date="20250201",
                )
            assert not df.empty
            result_collector.record(
                TestResult(
                    test_name="akshare_eastmoney_index_sh000001",
                    category="data_source",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={"rows": len(df), "columns": list(df.columns)},
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name="akshare_eastmoney_index_sh000001",
                    category="data_source",
                    status="fail",
                    error=f"{type(exc).__name__}: {exc}",
                    details={"traceback": traceback.format_exc()},
                )
            )
            pytest.fail(f"Index sh000001 failed: {exc}")

    def test_northbound_flow(self, rate_guard, result_collector):
        """Fetch northbound capital flow history."""
        import akshare as ak

        rate_guard.wait()
        try:
            with _bypass_proxy(), measure_time() as timing:
                df = ak.stock_hsgt_hist_em(symbol="北向资金")
            assert not df.empty
            result_collector.record(
                TestResult(
                    test_name="akshare_eastmoney_northbound_flow",
                    category="data_source",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={"rows": len(df), "columns": list(df.columns)},
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name="akshare_eastmoney_northbound_flow",
                    category="data_source",
                    status="fail",
                    error=f"{type(exc).__name__}: {exc}",
                    details={"traceback": traceback.format_exc()},
                )
            )
            pytest.fail(f"Northbound flow failed: {exc}")

    def test_margin_data(self, rate_guard, result_collector):
        """Fetch SSE margin trading data."""
        import akshare as ak

        rate_guard.wait()
        try:
            with _bypass_proxy(), measure_time() as timing:
                df = ak.stock_margin_sse(
                    start_date="20250101",
                    end_date="20250201",
                )
            assert not df.empty
            result_collector.record(
                TestResult(
                    test_name="akshare_eastmoney_margin_sse",
                    category="data_source",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={"rows": len(df), "columns": list(df.columns)},
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name="akshare_eastmoney_margin_sse",
                    category="data_source",
                    status="fail",
                    error=f"{type(exc).__name__}: {exc}",
                    details={"traceback": traceback.format_exc()},
                )
            )
            pytest.fail(f"Margin SSE data failed: {exc}")

    def test_dragon_tiger(self, rate_guard, result_collector):
        """Dragon tiger list -- may be empty outside trading hours."""
        import akshare as ak

        rate_guard.wait()
        try:
            with _bypass_proxy(), measure_time() as timing:
                df = ak.stock_lhb_detail_em(
                    start_date="20250101",
                    end_date="20250201",
                )
            # May be empty for recent dates with no dragon tiger activity
            assert isinstance(df, pd.DataFrame)
            result_collector.record(
                TestResult(
                    test_name="akshare_eastmoney_dragon_tiger",
                    category="data_source",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={
                        "rows": len(df),
                        "columns": list(df.columns) if not df.empty else [],
                    },
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name="akshare_eastmoney_dragon_tiger",
                    category="data_source",
                    status="fail",
                    error=f"{type(exc).__name__}: {exc}",
                    details={"traceback": traceback.format_exc()},
                )
            )
            pytest.fail(f"Dragon tiger list failed: {exc}")

    def test_limit_up_pool(self, rate_guard, result_collector):
        """Fetch limit-up stock pool for a specific date."""
        import akshare as ak

        rate_guard.wait()
        try:
            with _bypass_proxy(), measure_time() as timing:
                df = ak.stock_zt_pool_em(date="20250120")
            assert isinstance(df, pd.DataFrame)
            result_collector.record(
                TestResult(
                    test_name="akshare_eastmoney_limit_up_pool",
                    category="data_source",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={
                        "rows": len(df),
                        "columns": list(df.columns) if not df.empty else [],
                    },
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name="akshare_eastmoney_limit_up_pool",
                    category="data_source",
                    status="fail",
                    error=f"{type(exc).__name__}: {exc}",
                    details={"traceback": traceback.format_exc()},
                )
            )
            pytest.fail(f"Limit-up pool failed: {exc}")

    def test_fund_flow(self, rate_guard, result_collector):
        """Fetch individual stock fund flow for Moutai."""
        import akshare as ak

        rate_guard.wait()
        try:
            with _bypass_proxy(), measure_time() as timing:
                df = ak.stock_individual_fund_flow(
                    stock="600519",
                    market="sh",
                )
            assert isinstance(df, pd.DataFrame)
            result_collector.record(
                TestResult(
                    test_name="akshare_eastmoney_fund_flow_600519",
                    category="data_source",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={
                        "rows": len(df),
                        "columns": list(df.columns) if not df.empty else [],
                    },
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name="akshare_eastmoney_fund_flow_600519",
                    category="data_source",
                    status="fail",
                    error=f"{type(exc).__name__}: {exc}",
                    details={"traceback": traceback.format_exc()},
                )
            )
            pytest.fail(f"Fund flow 600519 failed: {exc}")

    def test_analyst_rank(self, rate_guard, result_collector):
        """Fetch analyst ranking from EastMoney."""
        import akshare as ak

        rate_guard.wait()
        try:
            with _bypass_proxy(), measure_time() as timing:
                df = ak.stock_analyst_rank_em()
            assert not df.empty
            result_collector.record(
                TestResult(
                    test_name="akshare_eastmoney_analyst_rank",
                    category="data_source",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={"rows": len(df), "columns": list(df.columns)},
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name="akshare_eastmoney_analyst_rank",
                    category="data_source",
                    status="fail",
                    error=f"{type(exc).__name__}: {exc}",
                    details={"traceback": traceback.format_exc()},
                )
            )
            pytest.fail(f"Analyst rank failed: {exc}")


# ---------------------------------------------------------------------------
# Sina real-time spot data
# ---------------------------------------------------------------------------


class TestAKShareSpot:
    """Sina real-time spot data via AKShare."""

    def test_spot_all_a_shares(self, rate_guard, result_collector):
        """Fetch real-time spot quotes for all A-share stocks."""
        import akshare as ak

        rate_guard.wait()
        try:
            with _bypass_proxy(), measure_time() as timing:
                df = ak.stock_zh_a_spot()
            assert len(df) > 3000  # ~5000 A-share stocks
            result_collector.record(
                TestResult(
                    test_name="akshare_sina_spot_all_a",
                    category="data_source",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={"rows": len(df), "columns": list(df.columns)},
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name="akshare_sina_spot_all_a",
                    category="data_source",
                    status="fail",
                    error=f"{type(exc).__name__}: {exc}",
                    details={"traceback": traceback.format_exc()},
                )
            )
            pytest.fail(f"Spot all A-shares failed: {exc}")

    def test_news_anomalies(self, rate_guard, result_collector):
        """Fetch real-time large buy anomaly alerts."""
        import akshare as ak

        rate_guard.wait()
        try:
            with _bypass_proxy(), measure_time() as timing:
                df = ak.stock_changes_em(symbol="大笔买入")
            assert isinstance(df, pd.DataFrame)
            result_collector.record(
                TestResult(
                    test_name="akshare_eastmoney_changes_large_buy",
                    category="data_source",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={
                        "rows": len(df),
                        "columns": list(df.columns) if not df.empty else [],
                    },
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name="akshare_eastmoney_changes_large_buy",
                    category="data_source",
                    status="fail",
                    error=f"{type(exc).__name__}: {exc}",
                    details={"traceback": traceback.format_exc()},
                )
            )
            pytest.fail(f"News anomalies (large buy) failed: {exc}")
