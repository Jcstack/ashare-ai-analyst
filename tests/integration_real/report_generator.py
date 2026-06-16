#!/usr/bin/env python3
"""Generate Markdown report from real integration test results.

Usage:
    python tests/integration_real/report_generator.py              # auto-detect
    python tests/integration_real/report_generator.py --report-only # from existing JSON
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"
RESULTS_FILE = REPORTS_DIR / "integration-real-results.json"
REPORT_FILE = REPORTS_DIR / "integration-real-report.md"


def load_results(path: Path = RESULTS_FILE) -> dict:
    if not path.exists():
        print(f"ERROR: {path} not found. Run tests first.")
        sys.exit(1)
    return json.loads(path.read_text())


def _grade(pass_rate: float) -> str:
    if pass_rate >= 0.98:
        return "A+"
    if pass_rate >= 0.95:
        return "A"
    if pass_rate >= 0.90:
        return "B+"
    if pass_rate >= 0.80:
        return "B"
    if pass_rate >= 0.70:
        return "C"
    if pass_rate >= 0.50:
        return "D"
    return "F"


def generate_report(data: dict) -> str:
    results = data.get("results", [])
    summary = data.get("summary", {})
    duration = data.get("total_duration_s", 0)
    generated = data.get("generated_at", datetime.now().isoformat())

    total = summary.get("total", len(results))
    passed = summary.get("passed", 0)
    failed = summary.get("failed", 0)
    skipped = summary.get("skipped", 0)
    errored = summary.get("errored", 0)
    pass_rate = passed / total if total > 0 else 0

    lines: list[str] = []
    w = lines.append

    # ---- Header ----
    w("# A-Share Platform Real Integration Test Report")
    w("")
    w(f"**Generated**: {generated}")
    w(f"**Duration**: {duration:.1f} seconds")
    w(f"**Overall Grade**: {_grade(pass_rate)}")
    w("")

    # ---- Executive Summary ----
    w("## Executive Summary")
    w("")
    w("| Metric | Value |")
    w("|--------|-------|")
    w(f"| Total Tests | {total} |")
    w(f"| Passed | {passed} |")
    w(f"| Failed | {failed} |")
    w(f"| Skipped | {skipped} |")
    w(f"| Errored | {errored} |")
    w(f"| Pass Rate | {pass_rate:.1%} |")
    w("")

    # ---- By Category ----
    categories: dict[str, list[dict]] = {}
    for r in results:
        cat = r.get("category", "unknown")
        categories.setdefault(cat, []).append(r)

    # ---- Data Source Health ----
    ds_results = categories.get("data_source", [])
    if ds_results:
        w("## Data Source Health")
        w("")
        w("| Source | Status | Latency (ms) | Details |")
        w("|--------|--------|-------------|---------|")
        for r in ds_results:
            name = r["test_name"]
            status = "PASS" if r["status"] == "pass" else "FAIL"
            lat = f"{r['latency_ms']:.0f}" if r["latency_ms"] else "-"
            details_dict = r.get("details", {})
            detail_str = ", ".join(
                f"{k}={v}" for k, v in details_dict.items() if k != "columns"
            )[:80]
            w(f"| {name} | {status} | {lat} | {detail_str} |")
        w("")

    # ---- LLM Provider Health ----
    llm_results = categories.get("llm", [])
    if llm_results:
        w("## LLM Provider Health")
        w("")
        w("| Provider | Model | Latency (ms) | Tokens (in/out) | Cost ($) | Status |")
        w("|----------|-------|-------------|-----------------|----------|--------|")
        for r in llm_results:
            d = r.get("details", {})
            provider = d.get("provider", r["test_name"])
            model = d.get("model", "-")
            lat = f"{r['latency_ms']:.0f}" if r["latency_ms"] else "-"
            tokens_in = d.get("input_tokens", "-")
            tokens_out = d.get("output_tokens", "-")
            cost = d.get("cost_usd", 0)
            cost_str = f"${cost:.6f}" if cost else "-"
            status = "OK" if r["status"] == "pass" else r["status"].upper()
            w(
                f"| {provider} | {model} | {lat} | {tokens_in}/{tokens_out} | {cost_str} | {status} |"
            )
        w("")

    # ---- API Endpoint Performance ----
    api_results = categories.get("api_endpoint", [])
    if api_results:
        w("## API Endpoint Performance")
        w("")

        # Summary stats
        api_latencies = [r["latency_ms"] for r in api_results if r["latency_ms"] > 0]
        if api_latencies:
            w(f"- **Endpoints tested**: {len(api_results)}")
            w(f"- **Avg latency**: {statistics.mean(api_latencies):.0f}ms")
            w(f"- **p50 latency**: {statistics.median(api_latencies):.0f}ms")
            sorted_lat = sorted(api_latencies)
            p95_idx = int(len(sorted_lat) * 0.95)
            w(
                f"- **p95 latency**: {sorted_lat[min(p95_idx, len(sorted_lat) - 1)]:.0f}ms"
            )
            w(f"- **Max latency**: {max(api_latencies):.0f}ms")
            w("")

        # Table — sorted by latency descending
        sorted_api = sorted(api_results, key=lambda r: r["latency_ms"], reverse=True)
        w("| Endpoint | Latency (ms) | Status | HTTP Code |")
        w("|----------|-------------|--------|-----------|")
        for r in sorted_api[:30]:  # Top 30
            d = r.get("details", {})
            name = (
                r["test_name"].replace("api_GET_", "GET ").replace("api_POST_", "POST ")
            )
            lat = f"{r['latency_ms']:.0f}"
            status = "PASS" if r["status"] == "pass" else "FAIL"
            code = d.get("status_code", "-")
            w(f"| {name} | {lat} | {status} | {code} |")
        w("")

    # ---- Fallback Chain Results ----
    fb_results = categories.get("fallback", [])
    if fb_results:
        w("## Fallback Chain Results")
        w("")
        w("| Chain | Source Used | Latency (ms) | Status |")
        w("|-------|-----------|-------------|--------|")
        for r in fb_results:
            d = r.get("details", {})
            chain = d.get("chain", r["test_name"])
            source = d.get("source_used", "-")
            lat = f"{r['latency_ms']:.0f}" if r["latency_ms"] else "-"
            status = "PASS" if r["status"] == "pass" else "FAIL"
            w(f"| {chain} | {source} | {lat} | {status} |")
        w("")

    # ---- Security Audit ----
    sec_results = categories.get("security", [])
    if sec_results:
        w("## Security Audit")
        w("")
        sec_passed = sum(1 for r in sec_results if r["status"] == "pass")
        sec_total = len(sec_results)
        w(f"**{sec_passed}/{sec_total} checks passed**")
        w("")

        # Group by test type
        sec_groups: dict[str, list[dict]] = {}
        for r in sec_results:
            name = r["test_name"]
            if "injection" in name:
                group = "Injection Prevention"
            elif "key" in name or "masked" in name:
                group = "API Key Safety"
            elif "process_time" in name:
                group = "Security Headers"
            else:
                group = "Error Sanitization"
            sec_groups.setdefault(group, []).append(r)

        for group_name, group_results in sec_groups.items():
            group_pass = sum(1 for r in group_results if r["status"] == "pass")
            w(f"### {group_name} ({group_pass}/{len(group_results)})")
            w("")
            failures = [r for r in group_results if r["status"] != "pass"]
            if failures:
                for r in failures[:5]:
                    w(f"- **FAIL** {r['test_name']}: {r.get('error', 'unknown')}")
            else:
                w("All checks passed.")
            w("")

    # ---- Real-time Performance ----
    rt_results = categories.get("realtime", [])
    if rt_results:
        w("## Real-time Performance")
        w("")
        w("| Metric | Value |")
        w("|--------|-------|")
        for r in rt_results:
            d = r.get("details", {})
            if "interval_seconds" in d:
                w(f"| SSE Event Interval | {d['interval_seconds']}s (target: 10s) |")
            if "p50_ms" in d:
                w(f"| Quote Refresh p50 | {d['p50_ms']:.0f}ms |")
                w(f"| Quote Refresh p95 | {d['p95_ms']:.0f}ms |")
            if "speedup_factor" in d and "uncached_ms" in d:
                w(f"| Uncached Latency | {d['uncached_ms']:.0f}ms |")
                w(f"| Cached Latency | {d['cached_ms']:.0f}ms |")
                w(f"| Cache Speedup | {d['speedup_factor']:.1f}x |")
            if "wall_time_ms" in d:
                w(
                    f"| Concurrent ({d.get('total_requests', '?')} requests) | {d['wall_time_ms']:.0f}ms total |"
                )
        w("")

    # ---- Stability ----
    stab_results = categories.get("stability", [])
    if stab_results:
        w("## Stability & Reliability")
        w("")
        w("| Test | Result | Key Metric |")
        w("|------|--------|-----------|")
        for r in stab_results:
            d = r.get("details", {})
            name = r["test_name"]
            status = "PASS" if r["status"] == "pass" else "FAIL"
            if "success_rate" in d:
                metric = (
                    f"{d['success_rate']:.1%} success ({d.get('total_polls', 0)} polls)"
                )
            elif "growth_mb" in d:
                metric = f"+{d['growth_mb']:.1f}MB memory ({d.get('requests_made', 0)} requests)"
            elif "speedup_factor" in d:
                metric = f"{d['speedup_factor']:.1f}x cache speedup"
            elif "cache_hit" in d:
                metric = f"Cache hit: {d['cache_hit']}"
            else:
                metric = "-"
            w(f"| {name} | {status} | {metric} |")
        w("")

    # ---- Prerequisites ----
    prereq_results = categories.get("prerequisite", [])
    if prereq_results:
        w("## Prerequisites & Environment")
        w("")
        w("| Check | Status | Details |")
        w("|-------|--------|---------|")
        for r in prereq_results:
            d = r.get("details", {})
            name = r["test_name"]
            status = "OK" if r["status"] == "pass" else r["status"].upper()
            detail_str = ", ".join(f"{k}={v}" for k, v in d.items())[:60]
            w(f"| {name} | {status} | {detail_str} |")
        w("")

    # ---- Failed Tests ----
    failed_tests = [r for r in results if r["status"] in ("fail", "error")]
    if failed_tests:
        w("## Failed Tests")
        w("")
        w("| Test | Category | Error |")
        w("|------|----------|-------|")
        for r in failed_tests[:20]:
            name = r["test_name"]
            cat = r["category"]
            err = r.get("error", "")[:100]
            w(f"| {name} | {cat} | {err} |")
        w("")

    # ---- Recommendations ----
    w("## Recommendations")
    w("")
    recommendations: list[str] = []

    # Check for slow endpoints
    slow_endpoints = [
        r for r in api_results if r["latency_ms"] > 10000 and r["status"] == "pass"
    ]
    if slow_endpoints:
        names = ", ".join(r["test_name"] for r in slow_endpoints[:3])
        recommendations.append(
            f"**Slow endpoints** (>10s): {names} — consider caching or async optimization"
        )

    # Check for data source failures
    ds_failures = [r for r in ds_results if r["status"] != "pass"]
    if ds_failures:
        names = ", ".join(r["test_name"] for r in ds_failures[:3])
        recommendations.append(
            f"**Data source issues**: {names} — review retry/fallback configuration"
        )

    # Check for security failures
    sec_failures = [r for r in sec_results if r["status"] != "pass"]
    if sec_failures:
        recommendations.append(
            f"**Security**: {len(sec_failures)} check(s) failed — review input validation"
        )

    # Check for LLM issues
    llm_failures = [r for r in llm_results if r["status"] != "pass"]
    if llm_failures:
        recommendations.append(
            "**LLM providers**: Some provider(s) failed — check API keys and quotas"
        )

    if not recommendations:
        w("No critical issues found. System is healthy.")
    else:
        for i, rec in enumerate(recommendations, 1):
            w(f"{i}. {rec}")
    w("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate integration test report")
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Generate report from existing JSON results",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=RESULTS_FILE,
        help="Path to results JSON file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPORT_FILE,
        help="Path to output Markdown report",
    )
    args = parser.parse_args()

    data = load_results(args.input)
    report = generate_report(data)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report)
    print(f"Report written to {args.output}")

    # Print summary
    s = data.get("summary", {})
    print(
        f"  {s.get('total', 0)} tests: "
        f"{s.get('passed', 0)} passed, "
        f"{s.get('failed', 0)} failed, "
        f"{s.get('skipped', 0)} skipped"
    )


if __name__ == "__main__":
    main()
