#!/usr/bin/env python3
"""Performance & Stability Test Runner with Report Generation.

Executes all performance and dependency stability tests, collects results
from JSON output files, and generates a comprehensive Markdown report.

Usage:
    python scripts/run_perf_tests.py              # Run all perf tests + generate report
    python scripts/run_perf_tests.py --report-only # Generate report from existing results
    python scripts/run_perf_tests.py --suite load  # Run only load tests
    python scripts/run_perf_tests.py --suite stability  # Run only stability tests
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = ROOT / "reports"
PERF_RESULTS = REPORTS_DIR / "perf-results.json"
STABILITY_RESULTS = REPORTS_DIR / "stability-results.json"
REPORT_OUTPUT = REPORTS_DIR / "performance-report.md"
PYTEST = str(ROOT / ".venv" / "bin" / "pytest")


def run_pytest(test_path: str, extra_args: list[str] | None = None) -> tuple[int, str]:
    """Run pytest and capture output."""
    cmd = [
        PYTEST, test_path,
        "-v", "--tb=short",
        "-m", "performance",
        "--no-header",
    ]
    if extra_args:
        cmd.extend(extra_args)

    print(f"\n{'='*60}")
    print(f"  Running: {' '.join(cmd)}")
    print(f"{'='*60}\n")

    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(ROOT), timeout=600,
    )
    output = result.stdout + result.stderr
    print(output[-3000:] if len(output) > 3000 else output)
    return result.returncode, output


def run_load_tests() -> int:
    """Run load and stress performance tests."""
    code, _ = run_pytest(
        "tests/performance/test_load_and_stress.py",
        ["--benchmark-disable"],
    )
    return code


def run_stability_tests() -> int:
    """Run dependency stability tests."""
    code1, _ = run_pytest(
        "tests/performance/test_dependency_stability.py",
        ["--benchmark-disable"],
    )
    code2, _ = run_pytest(
        "tests/performance/test_dependency_latency.py",
        ["--benchmark-disable"],
    )
    return max(code1, code2)


def run_existing_perf_benchmarks() -> int:
    """Run existing pytest-benchmark tests."""
    code, _ = run_pytest(
        "tests/performance/",
        ["--benchmark-only", "--benchmark-json=" + str(REPORTS_DIR / "benchmark.json")],
    )
    return code


def load_json(path: Path) -> dict:
    """Load JSON results file, return empty dict if missing."""
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _pct_bar(value: float, max_val: float = 100.0, width: int = 20) -> str:
    """Render a text-based percentage bar."""
    filled = int((value / max_val) * width) if max_val > 0 else 0
    filled = min(filled, width)
    return f"[{'█' * filled}{'░' * (width - filled)}]"


def _latency_grade(p95_ms: float) -> str:
    """Assign a grade based on p95 latency."""
    if p95_ms < 50:
        return "A+"
    if p95_ms < 100:
        return "A"
    if p95_ms < 200:
        return "B"
    if p95_ms < 500:
        return "C"
    if p95_ms < 1000:
        return "D"
    return "F"


def _error_grade(error_rate: float) -> str:
    """Assign a grade based on error rate."""
    if error_rate == 0:
        return "A+"
    if error_rate < 0.01:
        return "A"
    if error_rate < 0.05:
        return "B"
    if error_rate < 0.10:
        return "C"
    return "F"


def generate_report() -> str:
    """Generate comprehensive Markdown performance report."""
    perf = load_json(PERF_RESULTS)
    stability = load_json(STABILITY_RESULTS)
    benchmark = load_json(REPORTS_DIR / "benchmark.json")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = []

    def w(text: str = "") -> None:
        lines.append(text)

    # ── Header ────────────────────────────────────────────────
    w("# Performance & Stability Test Report")
    w(f"\n**Generated:** {now}")
    w("**Platform:** A-Share Intelligent Analysis Platform")
    w("**Test Environment:** Local (mocked external dependencies)")
    w()

    # ── Executive Summary ─────────────────────────────────────
    w("## 1. Executive Summary")
    w()

    total_endpoints = 0
    total_errors = 0
    total_samples = 0
    slowest_endpoint = ("", 0.0)
    fastest_endpoint = ("", float("inf"))

    if perf.get("endpoints"):
        for path, data in perf["endpoints"].items():
            total_endpoints += 1
            total_samples += data.get("samples", 0)
            er = data.get("error_rate", 0)
            total_errors += int(er * data.get("samples", 0))
            p95 = data.get("p95_ms", 0)
            if p95 > slowest_endpoint[1]:
                slowest_endpoint = (path, p95)
            if p95 < fastest_endpoint[1]:
                fastest_endpoint = (path, p95)

    overall_error_rate = (total_errors / total_samples * 100) if total_samples > 0 else 0

    w("| Metric | Value |")
    w("|--------|-------|")
    w(f"| Endpoints Tested | {total_endpoints} |")
    w(f"| Total Requests | {total_samples:,} |")
    w(f"| Overall Error Rate | {overall_error_rate:.2f}% |")
    w(f"| Slowest Endpoint (p95) | `{slowest_endpoint[0]}` ({slowest_endpoint[1]:.1f}ms) |")
    if fastest_endpoint[1] < float("inf"):
        w(f"| Fastest Endpoint (p95) | `{fastest_endpoint[0]}` ({fastest_endpoint[1]:.1f}ms) |")
    w()

    # Load test summary
    if perf.get("load_tests"):
        lt = perf["load_tests"]
        w(f"| Max Sustainable Concurrency | {lt.get('max_concurrency', 'N/A')} |")
        w(f"| Peak Throughput (req/s) | {lt.get('peak_rps', 'N/A')} |")
    w()

    # Stability summary
    if stability.get("fallback_tests"):
        ft = stability["fallback_tests"]
        total_fb = sum(v.get("passed", 0) + v.get("failed", 0) for v in ft.values())
        passed_fb = sum(v.get("passed", 0) for v in ft.values())
        w(f"| Fallback Scenarios Tested | {total_fb} |")
        w(f"| Fallback Success Rate | {passed_fb}/{total_fb} ({passed_fb/total_fb*100:.0f}%) |" if total_fb > 0 else "")
    w()

    # ── Endpoint Latency Table ────────────────────────────────
    w("## 2. Endpoint Latency Profile")
    w()
    w("### 2.1 Per-Endpoint Latency (sorted by p95)")
    w()
    w("| Endpoint | Method | Category | p50 (ms) | p95 (ms) | p99 (ms) | Mean (ms) | Grade |")
    w("|----------|--------|----------|----------|----------|----------|-----------|-------|")

    if perf.get("endpoints"):
        sorted_eps = sorted(
            perf["endpoints"].items(),
            key=lambda x: x[1].get("p95_ms", 0),
            reverse=True,
        )
        for path, data in sorted_eps:
            grade = _latency_grade(data.get("p95_ms", 0))
            w(
                f"| `{path}` | {data.get('method', 'GET')} | {data.get('category', '-')} "
                f"| {data.get('p50_ms', 0):.1f} | {data.get('p95_ms', 0):.1f} "
                f"| {data.get('p99_ms', 0):.1f} | {data.get('mean_ms', 0):.1f} | {grade} |"
            )
    else:
        w("| *(no data collected)* | | | | | | | |")
    w()

    # ── Category Summary ──────────────────────────────────────
    w("### 2.2 Latency by Category")
    w()

    categories: dict[str, list[float]] = {}
    if perf.get("endpoints"):
        for _, data in perf["endpoints"].items():
            cat = data.get("category", "unknown")
            categories.setdefault(cat, []).append(data.get("p95_ms", 0))

    if categories:
        w("| Category | Endpoints | Avg p95 (ms) | Max p95 (ms) | Grade |")
        w("|----------|-----------|-------------|-------------|-------|")
        for cat, vals in sorted(categories.items(), key=lambda x: max(x[1]), reverse=True):
            avg = sum(vals) / len(vals)
            mx = max(vals)
            w(f"| {cat} | {len(vals)} | {avg:.1f} | {mx:.1f} | {_latency_grade(mx)} |")
    w()

    # ── Error Rate Analysis ───────────────────────────────────
    w("## 3. Error Rate Analysis")
    w()
    w("| Endpoint | Method | Samples | Errors | Error Rate | Grade |")
    w("|----------|--------|---------|--------|------------|-------|")

    if perf.get("endpoints"):
        error_eps = sorted(
            perf["endpoints"].items(),
            key=lambda x: x[1].get("error_rate", 0),
            reverse=True,
        )
        for path, data in error_eps:
            er = data.get("error_rate", 0)
            samples = data.get("samples", 0)
            errors = int(er * samples)
            grade = _error_grade(er)
            w(
                f"| `{path}` | {data.get('method', 'GET')} | {samples} "
                f"| {errors} | {er*100:.1f}% | {grade} |"
            )

        # Error details
        error_details = {
            path: data.get("errors", {})
            for path, data in perf["endpoints"].items()
            if data.get("errors")
        }
        if error_details:
            w()
            w("### 3.1 Error Details")
            w()
            for path, errors in error_details.items():
                w(f"**`{path}`:**")
                for code, count in errors.items():
                    w(f"  - HTTP {code}: {count} occurrences")
                w()
    w()

    # ── Load Test Results ─────────────────────────────────────
    w("## 4. Load Test Results")
    w()

    if perf.get("load_tests"):
        lt = perf["load_tests"]
        if lt.get("concurrency_levels"):
            w("### 4.1 Throughput by Concurrency Level")
            w()
            w("| Concurrency | Requests/sec | Avg Latency (ms) | p95 Latency (ms) | Error Rate |")
            w("|-------------|-------------|-------------------|-------------------|------------|")
            for level in lt["concurrency_levels"]:
                w(
                    f"| {level['concurrency']} | {level.get('rps', 0):.1f} "
                    f"| {level.get('avg_ms', 0):.1f} | {level.get('p95_ms', 0):.1f} "
                    f"| {level.get('error_rate', 0)*100:.1f}% |"
                )
            w()

        if lt.get("stress_test"):
            st = lt["stress_test"]
            w("### 4.2 Stress Test (Escalation)")
            w()
            w(f"- **Breaking Point:** {st.get('breaking_concurrency', 'N/A')} concurrent requests")
            w(f"- **Max Sustainable Concurrency:** {st.get('max_sustainable', 'N/A')}")
            w(f"- **Error Rate at Break:** {st.get('break_error_rate', 0)*100:.1f}%")
            w()
    else:
        w("*(no load test data collected)*")
    w()

    # ── Dependency Stability ──────────────────────────────────
    w("## 5. Dependency Stability Report")
    w()

    if stability.get("fallback_tests"):
        w("### 5.1 Fallback Chain Results")
        w()
        w("| Dependency | Scenarios | Passed | Failed | Success Rate |")
        w("|-----------|-----------|--------|--------|-------------|")
        for dep, data in stability["fallback_tests"].items():
            p = data.get("passed", 0)
            f = data.get("failed", 0)
            total = p + f
            rate = (p / total * 100) if total > 0 else 0
            w(f"| {dep} | {total} | {p} | {f} | {rate:.0f}% |")
        w()

        # Detail entries
        for dep, data in stability["fallback_tests"].items():
            if data.get("details"):
                w(f"#### {dep}")
                w()
                for detail in data["details"]:
                    status = "PASS" if detail.get("passed") else "FAIL"
                    name = detail.get("test", detail.get("scenario", "unknown"))
                    w(f"- [{status}] {name}")
                    if detail.get("detail"):
                        w(f"  - {detail['detail']}")
                    if detail.get("error"):
                        w(f"  - Error: {detail['error']}")
                w()

    if stability.get("error_scenarios"):
        es = stability["error_scenarios"]
        w("### 5.2 Error Scenario Summary")
        w()
        w("| Metric | Value |")
        w("|--------|-------|")
        w(f"| Total Scenarios | {es.get('total_scenarios', 0)} |")
        w(f"| Graceful Handling | {es.get('graceful_handling', 0)} |")
        w(f"| Crashes | {es.get('crashes', 0)} |")
        w()

    if stability.get("latency_overhead"):
        lo = stability["latency_overhead"]
        w("### 5.3 Latency Overhead from Resilience Patterns")
        w()

        # Fallback overhead
        if lo.get("fallback_overhead_ms"):
            w("#### Fallback Overhead")
            w()
            w("| Path | Normal (ms) | Fallback (ms) | Overhead (ms) |")
            w("|------|-------------|--------------|---------------|")
            for name, data in lo["fallback_overhead_ms"].items():
                if isinstance(data, dict):
                    w(
                        f"| {name} | {data.get('normal_path_median_ms', 0):.2f} "
                        f"| {data.get('fallback_path_median_ms', 0):.2f} "
                        f"| {data.get('overhead_ms', 0):+.2f} |"
                    )
            w()

        # Retry overhead
        if lo.get("retry_overhead_ms"):
            w("#### Retry Overhead")
            w()
            w("| Source | Retries | Elapsed (ms) |")
            w("|--------|---------|-------------|")
            for name, data in lo["retry_overhead_ms"].items():
                if isinstance(data, dict):
                    for retry_key, retry_data in data.items():
                        if isinstance(retry_data, dict):
                            w(f"| {name} | {retry_key} | {retry_data.get('elapsed_ms', 0):.1f} |")
            w()

        # Cache speedup
        if lo.get("cache_speedup_factor"):
            w("#### Cache Effectiveness")
            w()
            w("| Cache | Hit (ms) | Miss (ms) | Speedup |")
            w("|-------|----------|-----------|---------|")
            for name, data in lo["cache_speedup_factor"].items():
                if isinstance(data, dict):
                    hit = data.get("cache_hit_median_ms", 0)
                    miss = data.get("cache_miss_median_ms", 0)
                    speedup = data.get("speedup_factor", "N/A")
                    if isinstance(speedup, (int, float)):
                        w(f"| {name} | {hit:.2f} | {miss:.2f} | {speedup:.1f}x |")
                    else:
                        w(f"| {name} | {hit:.2f} | {miss:.2f} | {speedup} |")
            w()

        # Connection pool
        if lo.get("connection_pool"):
            w("#### Connection Pool Performance")
            w()
            w("| Metric | Value |")
            w("|--------|-------|")
            for name, data in lo["connection_pool"].items():
                if isinstance(data, dict):
                    median = data.get("median_ms", data.get("single_dispatch_median_ms", ""))
                    if median != "":
                        w(f"| {name} | {median:.3f}ms median |")
            w()

    # ── Benchmark Results ─────────────────────────────────────
    if benchmark.get("benchmarks"):
        w("## 6. pytest-benchmark Baseline Results")
        w()
        w("| Test | Min (ms) | Mean (ms) | Max (ms) | StdDev | Rounds |")
        w("|------|----------|-----------|----------|--------|--------|")
        for bm in benchmark["benchmarks"]:
            stats = bm.get("stats", {})
            name = bm.get("name", "?")
            w(
                f"| {name} | {stats.get('min', 0)*1000:.2f} "
                f"| {stats.get('mean', 0)*1000:.2f} | {stats.get('max', 0)*1000:.2f} "
                f"| {stats.get('stddev', 0)*1000:.2f} | {stats.get('rounds', 0)} |"
            )
        w()

    # ── Bottleneck Identification ─────────────────────────────
    w("## 7. Identified Bottlenecks & Recommendations")
    w()

    bottlenecks: list[str] = []

    if perf.get("endpoints"):
        # Find slow endpoints
        slow_eps = [
            (p, d) for p, d in perf["endpoints"].items()
            if d.get("p95_ms", 0) > 200
        ]
        if slow_eps:
            bottlenecks.append(
                f"**{len(slow_eps)} endpoints exceed 200ms p95 threshold**"
            )
            for path, data in sorted(slow_eps, key=lambda x: x[1]["p95_ms"], reverse=True)[:5]:
                bottlenecks.append(f"  - `{path}`: {data['p95_ms']:.0f}ms p95")

        # Find high error endpoints
        error_eps = [
            (p, d) for p, d in perf["endpoints"].items()
            if d.get("error_rate", 0) > 0.01
        ]
        if error_eps:
            bottlenecks.append(
                f"**{len(error_eps)} endpoints have error rate > 1%**"
            )
            for path, data in error_eps:
                bottlenecks.append(
                    f"  - `{path}`: {data['error_rate']*100:.1f}% error rate"
                )

    if stability.get("fallback_tests"):
        for dep, data in stability["fallback_tests"].items():
            if data.get("failed", 0) > 0:
                bottlenecks.append(
                    f"**{dep}**: {data['failed']} fallback scenario(s) failed"
                )

    if not bottlenecks:
        w("No critical bottlenecks identified.")
    else:
        w("### 7.1 Bottlenecks")
        w()
        for b in bottlenecks:
            w(f"- {b}")
        w()

    # Standard recommendations
    w("### 7.2 Recommendations")
    w()
    w("| Priority | Area | Recommendation |")
    w("|----------|------|---------------|")

    if perf.get("endpoints"):
        slow_ai = [
            p for p, d in perf["endpoints"].items()
            if d.get("category") == "ai" and d.get("p95_ms", 0) > 500
        ]
        if slow_ai:
            w("| P0 | AI Endpoints | Add response caching with TTL for AI analysis results |")
            w("| P0 | AI Endpoints | Implement streaming responses (SSE) for long-running AI calls |")

        slow_data = [
            p for p, d in perf["endpoints"].items()
            if d.get("category") == "data" and d.get("p95_ms", 0) > 100
        ]
        if slow_data:
            w("| P1 | Data Endpoints | Review serialization overhead — consider orjson |")
            w("| P1 | Data Endpoints | Add in-memory LRU cache for frequently accessed data |")

    if stability.get("fallback_tests"):
        failed_any = any(
            d.get("failed", 0) > 0
            for d in stability["fallback_tests"].values()
        )
        if failed_any:
            w("| P0 | Resilience | Fix failing fallback scenarios — ensure graceful degradation |")
            w("| P1 | Resilience | Add circuit breaker pattern for flaky external APIs |")

    w("| P1 | External APIs | Implement request-level timeout budgets (total < 5s for data, < 15s for AI) |")
    w("| P2 | Monitoring | Add latency percentile tracking to production metrics |")
    w("| P2 | Caching | Implement stale-while-revalidate for market data endpoints |")
    w()

    # ── Dependency Health Matrix ──────────────────────────────
    w("## 8. External Dependency Health Matrix")
    w()
    w("| Dependency | Type | Fallback | Timeout | Retry | Cache | Circuit Breaker | Status |")
    w("|-----------|------|----------|---------|-------|-------|----------------|--------|")

    # Map dependency names to stability test keys for status lookup
    dep_test_keys = {
        "AKShare": ["data_source"],
        "adata": ["data_source"],
        "Sina Finance": ["data_source"],
        "Xueqiu": ["data_source"],
        "Yahoo Finance": ["data_source"],
        "Claude API": ["llm"],
        "OpenAI API": ["llm"],
        "Gemini API": ["llm"],
        "Redis": ["redis"],
        "Discord": ["webhook"],
        "WeChat Work": ["webhook"],
        "RSS Feeds": ["intelligence", "rss"],
        "Reddit API": ["intelligence", "reddit"],
    }

    deps = [
        ("AKShare", "Data", "adata", "10s", "3x", "12h parquet", "No"),
        ("adata", "Data", "None", "10s", "3x", "Shared", "No"),
        ("Sina Finance", "Realtime", "Xueqiu", "10s", "3x", "5s memory", "No"),
        ("Xueqiu", "Realtime", "adata", "10s", "3x", "Shared", "No"),
        ("Yahoo Finance", "Global", "Cache", "30s", "3x", "300s memory", "No"),
        ("Claude API", "LLM", "OpenAI/Gemini", "15s", "3x", "60s dedup", "No"),
        ("OpenAI API", "LLM", "Gemini/Claude", "15s", "3x", "60s dedup", "No"),
        ("Gemini API", "LLM", "Claude/OpenAI", "15s", "3x", "60s dedup", "No"),
        ("Redis", "Infra", "In-memory", "5s", "No", "N/A", "No"),
        ("Discord", "Webhook", "None", "10s", "3x", "N/A", "No"),
        ("WeChat Work", "Webhook", "None", "10s", "No", "N/A", "No"),
        ("RSS Feeds", "Intel", "Skip", "30s", "No", "300s", "No"),
        ("Reddit API", "Intel", "Skip", "10s", "No", "300s", "No"),
    ]

    for dep_name, dep_type, fallback, timeout, retry, cache, cb in deps:
        status = "Not Tested"
        if stability.get("fallback_tests"):
            search_keys = dep_test_keys.get(dep_name, [])
            for fb_key, fb_data in stability["fallback_tests"].items():
                if any(k in fb_key.lower() for k in search_keys):
                    status = "OK" if fb_data.get("failed", 0) == 0 else "ISSUE"
                    break
        # Also check error_scenarios
        if status == "Not Tested" and stability.get("error_scenarios"):
            for detail in stability["error_scenarios"].get("details", []):
                test_name = detail.get("test", "")
                search_keys = dep_test_keys.get(dep_name, [])
                if any(k in test_name.lower() for k in search_keys):
                    status = "OK" if detail.get("graceful") else "ISSUE"
                    break

        w(f"| {dep_name} | {dep_type} | {fallback} | {timeout} | {retry} | {cache} | {cb} | {status} |")
    w()

    # ── Footer ────────────────────────────────────────────────
    w("---")
    w(f"*Report generated by `scripts/run_perf_tests.py` at {now}*")
    w()

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Performance test runner")
    parser.add_argument(
        "--report-only", action="store_true",
        help="Skip tests, generate report from existing results",
    )
    parser.add_argument(
        "--suite", choices=["load", "stability", "benchmark", "all"],
        default="all", help="Which test suite to run",
    )
    args = parser.parse_args()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    exit_code = 0

    if not args.report_only:
        if args.suite in ("load", "all"):
            print("\n[1/3] Running load & stress tests...")
            code = run_load_tests()
            if code != 0:
                print(f"  WARNING: Load tests exited with code {code}")
                exit_code = max(exit_code, code)

        if args.suite in ("stability", "all"):
            print("\n[2/3] Running dependency stability tests...")
            code = run_stability_tests()
            if code != 0:
                print(f"  WARNING: Stability tests exited with code {code}")
                exit_code = max(exit_code, code)

        if args.suite in ("benchmark", "all"):
            print("\n[3/3] Running benchmark tests...")
            code = run_existing_perf_benchmarks()
            if code != 0:
                print(f"  WARNING: Benchmark tests exited with code {code}")
                exit_code = max(exit_code, code)

    print("\n[Report] Generating performance report...")
    report = generate_report()
    REPORT_OUTPUT.write_text(report)
    print(f"  Report written to: {REPORT_OUTPUT}")

    # Print summary to console
    print("\n" + "=" * 60)
    print("  PERFORMANCE TEST SUMMARY")
    print("=" * 60)

    perf = load_json(PERF_RESULTS)
    stability = load_json(STABILITY_RESULTS)

    if perf.get("endpoints"):
        total = len(perf["endpoints"])
        slow = sum(1 for d in perf["endpoints"].values() if d.get("p95_ms", 0) > 200)
        errors = sum(1 for d in perf["endpoints"].values() if d.get("error_rate", 0) > 0)
        print(f"  Endpoints: {total} tested, {slow} slow (>200ms p95), {errors} with errors")

    if stability.get("fallback_tests"):
        total = sum(
            v.get("passed", 0) + v.get("failed", 0)
            for v in stability["fallback_tests"].values()
        )
        failed = sum(v.get("failed", 0) for v in stability["fallback_tests"].values())
        print(f"  Stability: {total} scenarios, {failed} failures")

    print(f"\n  Full report: {REPORT_OUTPUT}")
    print(f"  Exit code: {exit_code}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
