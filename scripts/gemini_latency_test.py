"""Gemini API latency diagnostic — network vs model inference breakdown.

Usage: .venv/bin/python scripts/gemini_latency_test.py
"""

import os
import socket
import ssl
import statistics
import time

from dotenv import load_dotenv

load_dotenv()


def test_dns(
    host: str = "generativelanguage.googleapis.com", rounds: int = 5
) -> list[float]:
    times = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        socket.getaddrinfo(host, 443)
        times.append((time.perf_counter() - t0) * 1000)
    return times


def test_tcp_tls(
    host: str = "generativelanguage.googleapis.com", rounds: int = 5
) -> list[float]:
    times = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        ctx = ssl.create_default_context()
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        with socket.create_connection((host, 443), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=host):
                pass
        times.append((time.perf_counter() - t0) * 1000)
    return times


def test_gemini_call(prompt: str, model: str, max_tokens: int = 64) -> dict:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY", ""))
    config = types.GenerateContentConfig(
        max_output_tokens=max_tokens,
        temperature=0.1,
        http_options=types.HttpOptions(timeout=60000),
    )
    t0 = time.perf_counter()
    try:
        response = client.models.generate_content(
            model=model,
            contents=[{"role": "user", "parts": [prompt]}],
            config=config,
        )
        elapsed = (time.perf_counter() - t0) * 1000
        usage = getattr(response, "usage_metadata", None)
        return {
            "model": model,
            "elapsed_ms": elapsed,
            "input_tokens": getattr(usage, "prompt_token_count", 0) if usage else 0,
            "output_tokens": getattr(usage, "candidates_token_count", 0)
            if usage
            else 0,
            "output_chars": len(response.text) if response.text else 0,
            "error": None,
        }
    except Exception as e:
        return {
            "model": model,
            "elapsed_ms": (time.perf_counter() - t0) * 1000,
            "error": str(e),
        }


def fmt(times: list[float]) -> str:
    if not times:
        return "N/A"
    return (
        f"avg={statistics.mean(times):.0f}ms  "
        f"min={min(times):.0f}ms  max={max(times):.0f}ms  "
        f"p50={statistics.median(times):.0f}ms"
    )


def main() -> None:
    print("=" * 70)
    print("Gemini API Latency Diagnostic")
    print("=" * 70)

    print("\nDNS Resolution")
    print(f"  {fmt(test_dns())}")

    print("\nTCP + TLS Handshake")
    tls_times = test_tcp_tls()
    print(f"  {fmt(tls_times)}")

    models = ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-3-flash-preview"]

    print("\nTiny prompt: 'Say OK'")
    for model in models:
        results = []
        for i in range(3):
            r = test_gemini_call("Say OK", model, max_tokens=8)
            results.append(r)
            s = (
                f"{r['elapsed_ms']:.0f}ms"
                if not r["error"]
                else f"ERR: {r['error'][:60]}"
            )
            print(f"  [{model}] round {i + 1}: {s}")
        ok = [r["elapsed_ms"] for r in results if not r["error"]]
        if ok:
            print(f"  [{model}] {fmt(ok)}")
        print()

    print("Medium prompt: 3-stock review")
    medium = (
        "你是A股价值投资分析师。对以下3只股票简要评分(0-1)并给一句话理由。输出JSON数组。\n"
        "包钢股份(600010) 2.98 +1.36% PE=28.5\n"
        "四川黄金(001337) 49.90 +3.21% PE=45.2\n"
        "中国平安(601318) 52.30 -0.57% PE=9.8\n"
    )
    for model in models:
        results = []
        for i in range(2):
            r = test_gemini_call(medium, model, max_tokens=512)
            results.append(r)
            if r["error"]:
                print(f"  [{model}] round {i + 1}: ERR {r['error'][:60]}")
            else:
                print(
                    f"  [{model}] round {i + 1}: {r['elapsed_ms']:.0f}ms "
                    f"(in={r['input_tokens']} out={r['output_tokens']})"
                )
        ok = [r["elapsed_ms"] for r in results if not r["error"]]
        if ok:
            print(f"  [{model}] {fmt(ok)}")
        print()

    print("=" * 70)
    tls_avg = statistics.mean(tls_times)
    print(f"Network (TLS): {tls_avg:.0f}ms avg")
    if tls_avg > 500:
        print("  TLS > 500ms — GFW / routing issue likely")
    elif tls_avg > 200:
        print("  TLS 200-500ms — moderate, acceptable")
    else:
        print("  TLS < 200ms — network fine")


if __name__ == "__main__":
    main()
