"""Real-time quote source tests — Sina, Xueqiu, adata.

Each test makes REAL API calls to verify data source availability
and correctness.  No mocks.
"""

from __future__ import annotations

import pytest
import requests

from tests.integration_real.conftest import (
    TestResult,
    measure_time,
    requires_china_network,
)

pytestmark = [pytest.mark.integration_real, requires_china_network]


# ---------------------------------------------------------------------------
# Sina realtime (via AKShare ak.stock_zh_a_spot)
# ---------------------------------------------------------------------------


class TestSinaRealtime:
    """Verify Sina real-time quotes via AKShare."""

    def test_sina_spot_batch(self, result_collector, rate_guard):
        """Fetch A-share spot data and verify prices for known symbols.

        Soft-fail: Sina API is known to return HTML anti-bot pages under
        rate limiting.  Result is recorded in the collector for the report
        but the test does not hard-fail.
        """
        test_name = "sina_spot_batch"
        symbols = ["000001", "600519", "300750", "001330"]
        try:
            import akshare as ak

            from src.data.fetcher import _bypass_proxy

            rate_guard.wait()
            with measure_time() as timing:
                with _bypass_proxy():
                    df = ak.stock_zh_a_spot()

            if df is None or df.empty:
                result_collector.record(
                    TestResult(
                        test_name=test_name,
                        category="data_source",
                        status="fail",
                        error="ak.stock_zh_a_spot returned empty",
                    )
                )
                return

            # Normalize symbol column — strip exchange prefix if present
            sym_col = None
            for col in df.columns:
                if (
                    "代码" in str(col)
                    or "symbol" in str(col).lower()
                    or "code" in str(col).lower()
                ):
                    sym_col = col
                    break

            if sym_col is None:
                result_collector.record(
                    TestResult(
                        test_name=test_name,
                        category="data_source",
                        status="fail",
                        error=f"No symbol column found in {list(df.columns)}",
                    )
                )
                return

            df[sym_col] = (
                df[sym_col].astype(str).str.replace(r"^(sh|sz|bj)", "", regex=True)
            )

            # Find a price column
            price_col = None
            for col in df.columns:
                if (
                    "最新" in str(col)
                    or "price" in str(col).lower()
                    or "现价" in str(col)
                ):
                    price_col = col
                    break

            matched = 0
            if price_col:
                for sym in symbols:
                    row = df[df[sym_col] == sym]
                    if not row.empty:
                        price = float(row.iloc[0][price_col])
                        if price > 0:
                            matched += 1

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="pass" if matched >= 2 else "fail",
                    latency_ms=timing["elapsed_ms"],
                    details={"matched_symbols": matched, "total_rows": len(df)},
                    error=""
                    if matched >= 2
                    else f"Only matched {matched}/{len(symbols)}",
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="fail",
                    error=str(exc),
                )
            )

    def test_sina_latency_3_calls(self, result_collector, rate_guard):
        """Measure latency over 3 consecutive Sina calls.

        Soft-fail: Sina direct API may be blocked/rate-limited.
        """
        test_name = "sina_latency_3_calls"
        latencies: list[float] = []
        try:
            import akshare as ak

            from src.data.fetcher import _bypass_proxy

            for _ in range(3):
                rate_guard.wait()
                with measure_time() as timing:
                    with _bypass_proxy():
                        df = ak.stock_zh_a_spot()
                if df is None or df.empty:
                    break
                latencies.append(timing["elapsed_ms"])

            if len(latencies) >= 3:
                latencies_sorted = sorted(latencies)
                p50 = latencies_sorted[1]
                p95 = latencies_sorted[-1]
                result_collector.record(
                    TestResult(
                        test_name=test_name,
                        category="data_source",
                        status="pass",
                        latency_ms=p50,
                        details={
                            "p50_ms": round(p50, 1),
                            "p95_ms": round(p95, 1),
                            "all_ms": [round(lat, 1) for lat in latencies],
                        },
                    )
                )
            else:
                result_collector.record(
                    TestResult(
                        test_name=test_name,
                        category="data_source",
                        status="fail",
                        error=f"Only {len(latencies)}/3 calls succeeded",
                        details={
                            "latencies_collected": [round(lat, 1) for lat in latencies]
                        },
                    )
                )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="fail",
                    error=str(exc),
                    details={
                        "latencies_collected": [round(lat, 1) for lat in latencies]
                    },
                )
            )


# ---------------------------------------------------------------------------
# Xueqiu realtime
# ---------------------------------------------------------------------------


class TestXueqiuRealtime:
    """Verify Xueqiu quote API availability."""

    def test_xueqiu_session_init(self, result_collector, rate_guard):
        """Create a session, visit xueqiu.com, and verify xq_a_token cookie.

        Soft-fail: Xueqiu may change cookie mechanisms (anti-bot).
        """
        test_name = "xueqiu_session_init"
        try:
            rate_guard.wait()
            session = requests.Session()
            session.headers.update(
                {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                }
            )
            session.trust_env = False

            with measure_time() as timing:
                resp = session.get("https://xueqiu.com/", timeout=10)

            resp.raise_for_status()

            cookie_names = [c.name for c in session.cookies]
            has_token = "xq_a_token" in cookie_names

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="pass" if has_token else "fail",
                    latency_ms=timing["elapsed_ms"],
                    details={"cookies": cookie_names, "has_xq_a_token": has_token},
                    error=""
                    if has_token
                    else f"xq_a_token not found; got: {cookie_names}",
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="fail",
                    error=str(exc),
                )
            )

    def test_xueqiu_batch_quote(self, result_collector, rate_guard):
        """Fetch batch quotes from Xueqiu and verify response structure."""
        test_name = "xueqiu_batch_quote"
        try:
            rate_guard.wait()
            session = requests.Session()
            session.headers.update(
                {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                }
            )
            session.trust_env = False
            session.get("https://xueqiu.com/", timeout=10)

            rate_guard.wait()
            url = "https://stock.xueqiu.com/v5/stock/realtime/quotec.json"
            params = {"symbol": "SH600519,SZ000001"}

            with measure_time() as timing:
                resp = session.get(url, params=params, timeout=10)

            resp.raise_for_status()
            body = resp.json()

            assert "data" in body, f"Response missing 'data' key: {list(body.keys())}"
            data = body["data"]
            assert isinstance(data, list), f"data is not a list: {type(data)}"
            assert len(data) >= 1, "data list is empty"

            for item in data:
                assert "current" in item, (
                    f"Item missing 'current' key: {list(item.keys())}"
                )
                assert item["current"] is not None and item["current"] > 0, (
                    f"Invalid price: {item.get('current')}"
                )

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={
                        "symbols_returned": len(data),
                        "prices": {
                            item.get("symbol", "?"): item.get("current")
                            for item in data
                        },
                    },
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="fail",
                    error=str(exc),
                )
            )

    def test_xueqiu_symbol_prefix_mapping(self, result_collector):
        """Verify our symbol prefix logic matches Xueqiu conventions."""
        test_name = "xueqiu_symbol_prefix_mapping"
        try:
            mapping = {
                "600519": "SH600519",  # Shanghai
                "000001": "SZ000001",  # Shenzhen
                "300750": "SZ300750",  # ChiNext
                "688981": "SH688981",  # STAR
            }

            for code, expected in mapping.items():
                prefix = "SH" if code.startswith(("6", "9")) else "SZ"
                actual = f"{prefix}{code}"
                assert actual == expected, (
                    f"Mapping mismatch for {code}: expected {expected}, got {actual}"
                )

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="pass",
                    details={"mappings_verified": len(mapping)},
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="fail",
                    error=str(exc),
                )
            )


# ---------------------------------------------------------------------------
# adata realtime
# ---------------------------------------------------------------------------


class TestAdataRealtime:
    """Verify adata quote availability (optional dependency)."""

    def test_adata_available(self, result_collector):
        """Check whether adata is importable."""
        test_name = "adata_available"
        try:
            import adata  # noqa: F401

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="pass",
                    details={"adata_version": getattr(adata, "__version__", "unknown")},
                )
            )
        except ImportError:
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="skip",
                    details={"reason": "adata not installed"},
                )
            )

    def test_adata_current_quotes(self, result_collector, rate_guard):
        """Fetch current quotes via adata if available."""
        test_name = "adata_current_quotes"
        try:
            import adata
        except ImportError:
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="skip",
                    details={"reason": "adata not installed"},
                )
            )
            return

        try:
            rate_guard.wait()
            with measure_time() as timing:
                df = adata.stock.market.list_market_current(
                    code_list=["000001", "600519"],
                )

            has_data = df is not None and not df.empty
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="pass" if has_data else "fail",
                    latency_ms=timing["elapsed_ms"],
                    details={
                        "rows": len(df) if df is not None else 0,
                        "columns": list(df.columns)
                        if df is not None and not df.empty
                        else [],
                    },
                    error=""
                    if has_data
                    else "adata returned empty (may be after-hours)",
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="data_source",
                    status="fail",
                    error=str(exc),
                )
            )
