"""Real AI-powered analysis endpoint tests — NO mocks, real LLM calls.

These endpoints trigger real data gathering + real LLM inference, so
they have long timeouts (up to 120 seconds).  They require both China
network access (for data) and at least one LLM API key.

Rate-limiting uses ``llm_rate_guard`` (2-second interval) since every
request fans out to an LLM provider.
"""

from __future__ import annotations

import traceback

import pytest

from tests.integration_real.conftest import (
    TestResult,
    measure_time,
    requires_any_llm_key,
    requires_china_network,
)

pytestmark = [
    pytest.mark.integration_real,
    requires_china_network,
    requires_any_llm_key,
]


# ---------------------------------------------------------------------------
# AI analysis endpoints (long-running)
# ---------------------------------------------------------------------------


class TestAIAnalysis:
    """Endpoints that invoke real LLM inference on live market data."""

    def test_ai_analysis_000001(self, real_client, llm_rate_guard, result_collector):
        """GET /api/v1/stock/000001/ai-analysis — full AI analysis.

        This is the heaviest endpoint: fetches live data, computes
        indicators, then sends everything to an LLM for analysis.
        Timeout is set to 120 seconds.
        """
        llm_rate_guard.wait()
        test_name = "ai_analysis_000001"
        try:
            with measure_time() as timing:
                resp = real_client.get(
                    "/api/v1/stock/000001/ai-analysis",
                    timeout=120.0,
                )

            status = "pass" if 200 <= resp.status_code < 300 else "fail"
            details = {
                "status_code": resp.status_code,
                "response_size": len(resp.content),
                "process_time": resp.headers.get("X-Process-Time", "0"),
            }

            if status == "pass":
                data = resp.json()
                assert isinstance(data, dict), "AI analysis response should be a dict"
                details["response_keys"] = list(data.keys())[:10]

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="ai_analysis",
                    status=status,
                    latency_ms=timing["elapsed_ms"],
                    details=details,
                    error=""
                    if status == "pass"
                    else f"HTTP {resp.status_code}: {resp.text[:200]}",
                )
            )
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="ai_analysis",
                    status="error",
                    error=f"{type(exc).__name__}: {exc}",
                    details={"traceback": traceback.format_exc()},
                )
            )
            pytest.fail(f"AI analysis 000001 failed: {exc}")

    def test_predict_000001(self, real_client, llm_rate_guard, result_collector):
        """POST /api/v1/predict/000001 — stock price prediction.

        Runs the prediction pipeline with real data and LLM inference.
        """
        llm_rate_guard.wait()
        test_name = "predict_000001"
        try:
            with measure_time() as timing:
                resp = real_client.post(
                    "/api/v1/predict/000001",
                    timeout=120.0,
                )

            status = "pass" if 200 <= resp.status_code < 300 else "fail"
            details = {
                "status_code": resp.status_code,
                "response_size": len(resp.content),
                "process_time": resp.headers.get("X-Process-Time", "0"),
            }

            if status == "pass":
                data = resp.json()
                assert isinstance(data, dict), "Predict response should be a dict"
                details["response_keys"] = list(data.keys())[:10]

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="ai_analysis",
                    status=status,
                    latency_ms=timing["elapsed_ms"],
                    details=details,
                    error=""
                    if status == "pass"
                    else f"HTTP {resp.status_code}: {resp.text[:200]}",
                )
            )
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="ai_analysis",
                    status="error",
                    error=f"{type(exc).__name__}: {exc}",
                    details={"traceback": traceback.format_exc()},
                )
            )
            pytest.fail(f"Predict 000001 failed: {exc}")

    def test_advisor_000001(self, real_client, llm_rate_guard, result_collector):
        """GET /api/v1/advisor/stock/000001 — AI advisor recommendation.

        Produces a buy/hold/sell recommendation backed by LLM reasoning.
        """
        llm_rate_guard.wait()
        test_name = "advisor_000001"
        try:
            with measure_time() as timing:
                resp = real_client.get(
                    "/api/v1/advisor/stock/000001",
                    timeout=120.0,
                )

            status = "pass" if 200 <= resp.status_code < 300 else "fail"
            details = {
                "status_code": resp.status_code,
                "response_size": len(resp.content),
                "process_time": resp.headers.get("X-Process-Time", "0"),
            }

            if status == "pass":
                data = resp.json()
                assert isinstance(data, dict), "Advisor response should be a dict"
                details["response_keys"] = list(data.keys())[:10]

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="ai_analysis",
                    status=status,
                    latency_ms=timing["elapsed_ms"],
                    details=details,
                    error=""
                    if status == "pass"
                    else f"HTTP {resp.status_code}: {resp.text[:200]}",
                )
            )
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="ai_analysis",
                    status="error",
                    error=f"{type(exc).__name__}: {exc}",
                    details={"traceback": traceback.format_exc()},
                )
            )
            pytest.fail(f"Advisor 000001 failed: {exc}")

    def test_concept_hot(self, real_client, llm_rate_guard, result_collector):
        """GET /api/v1/concept/hot — hot concept themes.

        While this endpoint does not always require LLM calls, it
        involves complex data aggregation and may trigger AI enrichment
        depending on configuration.
        """
        llm_rate_guard.wait()
        test_name = "concept_hot_ai"
        try:
            with measure_time() as timing:
                resp = real_client.get(
                    "/api/v1/concept/hot",
                    timeout=120.0,
                )

            status = "pass" if 200 <= resp.status_code < 300 else "fail"
            details = {
                "status_code": resp.status_code,
                "response_size": len(resp.content),
                "process_time": resp.headers.get("X-Process-Time", "0"),
            }

            if status == "pass":
                data = resp.json()
                assert isinstance(data, (dict, list)), (
                    "Concept hot response should be dict or list"
                )
                if isinstance(data, dict):
                    details["response_keys"] = list(data.keys())[:10]
                elif isinstance(data, list):
                    details["item_count"] = len(data)

            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="ai_analysis",
                    status=status,
                    latency_ms=timing["elapsed_ms"],
                    details=details,
                    error=""
                    if status == "pass"
                    else f"HTTP {resp.status_code}: {resp.text[:200]}",
                )
            )
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name=test_name,
                    category="ai_analysis",
                    status="error",
                    error=f"{type(exc).__name__}: {exc}",
                    details={"traceback": traceback.format_exc()},
                )
            )
            pytest.fail(f"Concept hot failed: {exc}")
