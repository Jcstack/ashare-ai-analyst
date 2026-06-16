"""Real fallback chain validation — observe actual source selection behavior.

These tests do NOT artificially break sources. They observe real behavior
and document which source was used under current network conditions.
"""

from __future__ import annotations

import logging
import os

import pandas as pd
import pytest

from tests.integration_real.conftest import (
    TestResult,
    measure_time,
    requires_china_network,
)

pytestmark = [pytest.mark.integration_real, requires_china_network]


class TestOHLCVFallbackChain:
    """Observe the OHLCV 3-tier fallback: Tencent → EastMoney → adata."""

    def test_ohlcv_source_selection(self, rate_guard, result_collector, caplog):
        """Fetch OHLCV and capture which source was used via log output."""
        from src.data.fetcher import StockDataFetcher

        rate_guard.wait()
        fetcher = StockDataFetcher()
        source_used = "unknown"

        with caplog.at_level(logging.DEBUG, logger="data"), measure_time() as timing:
            try:
                df = fetcher.fetch_daily_ohlcv("600519")
                success = not df.empty and len(df) > 0
            except Exception as exc:
                df = pd.DataFrame()
                success = False
                source_used = f"error: {exc}"

        # Parse logs to detect source
        log_text = caplog.text.lower()
        if "tencent" in log_text or "hist_tx" in log_text:
            source_used = "tencent"
        elif "eastmoney" in log_text or "stock_zh_a_hist" in log_text:
            source_used = "eastmoney"
        elif "adata" in log_text:
            source_used = "adata"

        result_collector.record(
            TestResult(
                test_name="ohlcv_fallback_chain",
                category="fallback",
                status="pass" if success else "fail",
                latency_ms=timing["elapsed_ms"],
                details={
                    "source_used": source_used,
                    "rows": len(df) if success else 0,
                    "chain": "tencent → eastmoney → adata",
                },
            )
        )
        assert success, f"OHLCV fetch failed entirely. Source attempted: {source_used}"

    def test_source_router_health_state(self, rate_guard, result_collector):
        """Inspect DataSourceRouter health after real calls."""
        from src.data.source_router import DataSourceRouter

        router = DataSourceRouter()
        health = {}
        for domain in [
            "SINA",
            "EASTMONEY_PUSH2",
            "EASTMONEY_DATACENTER",
            "XUEQIU",
            "TENCENT",
            "ADATA",
        ]:
            try:
                status = router.get_domain_health(domain)
                health[domain] = str(status)
            except Exception:
                health[domain] = "unknown"

        result_collector.record(
            TestResult(
                test_name="source_router_health_state",
                category="fallback",
                status="pass",
                details={"health": health},
            )
        )


class TestRealtimeFallbackChain:
    """Observe the realtime quote fallback: Sina → Xueqiu → adata."""

    def test_realtime_source_selection(self, rate_guard, result_collector, caplog):
        """Fetch quotes and capture which source responded."""
        from src.data.realtime import RealtimeQuoteManager

        rate_guard.wait()
        mgr = RealtimeQuoteManager()
        source_used = "unknown"

        with caplog.at_level(logging.DEBUG, logger="data"), measure_time() as timing:
            try:
                df = mgr.get_quotes(["000001", "600519"])
                success = not df.empty
            except Exception as exc:
                df = pd.DataFrame()
                success = False
                source_used = f"error: {exc}"

        log_text = caplog.text.lower()
        if "sina" in log_text:
            source_used = "sina"
        elif "xueqiu" in log_text:
            source_used = "xueqiu"
        elif "adata" in log_text:
            source_used = "adata"

        result_collector.record(
            TestResult(
                test_name="realtime_fallback_chain",
                category="fallback",
                status="pass" if success else "fail",
                latency_ms=timing["elapsed_ms"],
                details={
                    "source_used": source_used,
                    "symbols_returned": len(df) if success else 0,
                    "chain": "sina → xueqiu → adata",
                },
            )
        )

    def test_realtime_all_symbols_returned(self, rate_guard, result_collector):
        """Verify all requested symbols get a quote (regardless of source)."""
        from src.data.realtime import RealtimeQuoteManager

        rate_guard.wait()
        mgr = RealtimeQuoteManager()
        symbols = ["000001", "600519"]

        try:
            with measure_time() as timing:
                df = mgr.get_quotes(symbols)
            returned = set(df["symbol"].tolist()) if not df.empty else set()
            missing = set(symbols) - returned
            status = "pass" if not missing else "fail"
            error = f"Missing symbols: {missing}" if missing else ""
        except Exception as exc:
            timing = {"elapsed_ms": 0}
            status = "fail"
            error = str(exc)
            missing = set(symbols)

        result_collector.record(
            TestResult(
                test_name="realtime_all_symbols_returned",
                category="fallback",
                status=status,
                latency_ms=timing.get("elapsed_ms", 0),
                details={"requested": symbols, "missing": list(missing)},
                error=error,
            )
        )


@pytest.mark.skipif(
    not any(
        bool(os.environ.get(k, "").strip())
        for k in ["GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"]
    ),
    reason="No LLM API key set",
)
class TestLLMFallbackChain:
    """Observe LLM router provider selection under real conditions."""

    def test_llm_provider_selection(self, llm_rate_guard, result_collector):
        """Send 1 real request through LLMRouter, observe provider chosen."""
        from src.llm.base import LLMMessage
        from src.llm.router import LLMRouter

        llm_rate_guard.wait()
        router = LLMRouter()

        try:
            with measure_time() as timing:
                response = router.complete(
                    messages=[LLMMessage(role="user", content='Return: {"ok": true}')],
                    max_tokens=30,
                    temperature=0,
                )
            result_collector.record(
                TestResult(
                    test_name="llm_fallback_provider_selection",
                    category="fallback",
                    status="pass",
                    latency_ms=timing["elapsed_ms"],
                    details={
                        "provider": str(response.provider),
                        "model": response.model,
                        "input_tokens": response.input_tokens,
                        "output_tokens": response.output_tokens,
                        "cost_usd": response.cost_usd,
                        "routing_strategy": "cost",
                    },
                )
            )
            assert response.text
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name="llm_fallback_provider_selection",
                    category="fallback",
                    status="fail",
                    error=str(exc),
                )
            )

    def test_llm_available_providers(self, result_collector):
        """Check which LLM providers are actually available."""
        from src.llm.router import LLMRouter

        router = LLMRouter()
        providers = (
            router.available_providers if hasattr(router, "available_providers") else []
        )

        result_collector.record(
            TestResult(
                test_name="llm_available_providers",
                category="fallback",
                status="pass" if providers else "fail",
                details={"providers": [str(p) for p in providers]},
            )
        )
