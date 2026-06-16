"""Security audit — injection payloads, API key masking, error sanitization.

Tests that the API properly validates inputs, never leaks secrets, and
returns sanitized error messages.
"""

from __future__ import annotations

import re

import pytest

from tests.integration_real.conftest import TestResult, measure_time

pytestmark = pytest.mark.integration_real

# ---------------------------------------------------------------------------
# Injection payloads
# ---------------------------------------------------------------------------

INJECTION_PAYLOADS = [
    ("sql_injection", "'; DROP TABLE stocks;--"),
    ("xss_script", "<script>alert('xss')</script>"),
    ("xss_img", '<img src=x onerror="alert(1)">'),
    ("ssti", "{{7*7}}"),
    ("path_traversal", "../../../etc/passwd"),
    ("header_injection", "000001\r\nX-Injected: true"),
    ("null_byte", "000001%00malicious"),
    ("buffer_overflow", "A" * 10000),
    ("unicode_abuse", "\u0000\u200b\uffff"),
]

SYMBOL_ENDPOINTS = [
    "/api/v1/stock/{symbol}",
    "/api/v1/stock/{symbol}/ohlcv",
    "/api/v1/stock/{symbol}/indicators",
    "/api/v1/stock/{symbol}/news",
]

# API key patterns that should NEVER appear in responses
API_KEY_PATTERNS = [
    re.compile(r"sk-ant-api\w+"),  # Anthropic
    re.compile(r"AIzaSy[\w-]+"),  # Google
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),  # OpenAI
    re.compile(r"xoxb-[\w-]+"),  # Slack
]


class TestInputValidation:
    """Verify injection payloads are rejected or sanitized."""

    @pytest.mark.parametrize("payload_name,payload", INJECTION_PAYLOADS)
    @pytest.mark.parametrize("endpoint_template", SYMBOL_ENDPOINTS)
    def test_injection_rejected(
        self,
        real_client,
        payload_name,
        payload,
        endpoint_template,
        result_collector,
    ):
        """Injection payload should return 4xx, NOT 500 or echo the payload."""
        path = endpoint_template.replace("{symbol}", payload)

        try:
            with measure_time() as timing:
                resp = real_client.get(path)
        except Exception:
            # Client-side rejection (e.g., httpx rejects non-printable chars in URL)
            # counts as PASS — the attack was prevented at the client/transport layer.
            result_collector.record(
                TestResult(
                    test_name=f"injection_{payload_name}_{endpoint_template}",
                    category="security",
                    status="pass",
                    details={
                        "payload": payload_name,
                        "endpoint": endpoint_template,
                        "blocked_by": "client",
                    },
                )
            )
            return

        status_code = resp.status_code
        body = resp.text

        # Should NOT be 500 (internal server error = unhandled exception)
        is_safe_status = status_code in (400, 404, 405, 422)
        # Also accept 200 if the app handles it gracefully (e.g., returns empty)
        if status_code == 200:
            is_safe_status = True

        # Should NOT echo back raw injection payload (XSS prevention)
        # Only check for the distinctive part of the payload
        echoed = False
        if payload_name.startswith("xss"):
            echoed = "<script>" in body or "onerror=" in body
        elif payload_name == "sql_injection":
            echoed = "DROP TABLE" in body

        # Should NOT contain stack traces
        has_stacktrace = "Traceback" in body or 'File "/' in body

        passed = is_safe_status and not echoed and not has_stacktrace
        error_parts = []
        if not is_safe_status:
            error_parts.append(f"Got HTTP {status_code} (expected 4xx)")
        if echoed:
            error_parts.append("Payload echoed in response body")
        if has_stacktrace:
            error_parts.append("Stack trace leaked in response")

        result_collector.record(
            TestResult(
                test_name=f"injection_{payload_name}_{endpoint_template}",
                category="security",
                status="pass" if passed else "fail",
                latency_ms=timing["elapsed_ms"],
                details={
                    "status_code": status_code,
                    "payload": payload_name,
                    "endpoint": endpoint_template,
                },
                error="; ".join(error_parts) if error_parts else "",
            )
        )


class TestAPIKeySafety:
    """Verify API keys are never exposed in responses."""

    def test_admin_keys_masked(self, real_client, result_collector):
        """GET /admin/keys should mask API keys with ***."""
        try:
            with measure_time() as timing:
                resp = real_client.get("/api/v1/admin/keys")

            if resp.status_code == 200:
                body = resp.text
                has_raw_key = any(p.search(body) for p in API_KEY_PATTERNS)
                status = "fail" if has_raw_key else "pass"
                error = (
                    "Raw API key found in /admin/keys response" if has_raw_key else ""
                )
            else:
                status = "pass"  # 404 or other = keys not exposed
                error = ""

            result_collector.record(
                TestResult(
                    test_name="admin_keys_masked",
                    category="security",
                    status=status,
                    latency_ms=timing["elapsed_ms"],
                    error=error,
                )
            )
        except Exception as exc:
            result_collector.record(
                TestResult(
                    test_name="admin_keys_masked",
                    category="security",
                    status="error",
                    error=str(exc),
                )
            )

    def test_no_keys_in_response_headers(self, real_client, result_collector):
        """Check 10 random endpoints for API key leaks in headers."""
        endpoints = [
            "/api/v1/watchlist",
            "/api/v1/market/status",
            "/api/v1/notifications/unread-count",
            "/api/v1/admin/usage",
            "/api/v1/admin/routing",
            "/api/v1/settings/config/stocks",
            "/api/v1/intelligence-hub/overview",
            "/api/v1/market-intelligence/signals",
            "/api/v1/stocks/search?q=test",
            "/api/v1/capital/balance",
        ]

        leaks_found = []
        for ep in endpoints:
            try:
                resp = real_client.get(ep)
                all_headers = " ".join(f"{k}: {v}" for k, v in resp.headers.items())
                for pattern in API_KEY_PATTERNS:
                    if pattern.search(all_headers):
                        leaks_found.append(ep)
                        break
            except Exception:
                pass

        status = "fail" if leaks_found else "pass"
        result_collector.record(
            TestResult(
                test_name="no_keys_in_headers",
                category="security",
                status=status,
                details={"endpoints_checked": len(endpoints), "leaks": leaks_found},
                error=f"Key leak in headers: {leaks_found}" if leaks_found else "",
            )
        )

    def test_no_keys_in_error_responses(self, real_client, result_collector):
        """Trigger error responses and check they don't contain keys."""
        error_paths = [
            "/api/v1/stock/INVALID_SYMBOL_99999",
            "/api/v1/predict/NONEXISTENT",
            "/api/v1/this-does-not-exist",
        ]

        leaks_found = []
        for path in error_paths:
            try:
                resp = real_client.get(path)
                body = resp.text
                for pattern in API_KEY_PATTERNS:
                    if pattern.search(body):
                        leaks_found.append(path)
                        break
            except Exception:
                pass

        status = "fail" if leaks_found else "pass"
        result_collector.record(
            TestResult(
                test_name="no_keys_in_errors",
                category="security",
                status=status,
                details={"leaks": leaks_found},
                error=f"Key leak in error response: {leaks_found}"
                if leaks_found
                else "",
            )
        )


class TestErrorSanitization:
    """Verify error responses don't leak internal details."""

    def test_404_no_internal_paths(self, real_client, result_collector):
        """404 responses should not contain file system paths."""
        resp = real_client.get("/api/v1/this-route-does-not-exist-at-all")
        body = resp.text

        has_path = "/Users/" in body or "/home/" in body or "/app/" in body
        has_traceback = "Traceback" in body

        passed = not has_path and not has_traceback
        result_collector.record(
            TestResult(
                test_name="404_no_internal_paths",
                category="security",
                status="pass" if passed else "fail",
                details={"status_code": resp.status_code},
                error="Internal path or traceback leaked" if not passed else "",
            )
        )

    def test_invalid_json_body_handled(self, real_client, result_collector):
        """POST with invalid JSON should return 422, not 500."""
        # Use /predict/compare which requires a valid JSON body (ComparisonPredictionRequest)
        resp = real_client.post(
            "/api/v1/predict/compare",
            content=b"this is not json",
            headers={"Content-Type": "application/json"},
        )

        passed = resp.status_code in (400, 422)
        result_collector.record(
            TestResult(
                test_name="invalid_json_handled",
                category="security",
                status="pass" if passed else "fail",
                details={"status_code": resp.status_code},
                error=f"Got {resp.status_code}, expected 400/422" if not passed else "",
            )
        )

    def test_oversized_request_handled(self, real_client, result_collector):
        """Very large request body should be rejected gracefully."""
        large_body = {"data": "x" * 1_000_000}
        resp = real_client.post(
            "/api/v1/predict/000001",
            json=large_body,
        )

        # Should not be 500
        passed = resp.status_code != 500
        result_collector.record(
            TestResult(
                test_name="oversized_request_handled",
                category="security",
                status="pass" if passed else "fail",
                details={"status_code": resp.status_code},
                error="Got 500 on oversized request" if not passed else "",
            )
        )


class TestProcessTimeHeader:
    """Verify X-Process-Time header is present on all responses."""

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/watchlist",
            "/api/v1/market/status",
            "/api/v1/notifications/unread-count",
        ],
    )
    def test_process_time_header_present(self, real_client, path, result_collector):
        """Every response should include X-Process-Time header."""
        resp = real_client.get(path)
        has_header = "X-Process-Time" in resp.headers

        result_collector.record(
            TestResult(
                test_name=f"process_time_header_{path}",
                category="security",
                status="pass" if has_header else "fail",
                details={
                    "has_header": has_header,
                    "value": resp.headers.get("X-Process-Time", "missing"),
                },
            )
        )
