"""Baseline performance test — run against a live service.

This script performs a quick baseline test without Locust, using only httpx.
Use it to verify the service is running and get initial latency numbers
before running the full Locust suite.

Usage:
    cd insight-ai-agent
    python tests/load/run_baseline.py --host http://localhost:5000
    python tests/load/run_baseline.py --host https://api.example.com
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time


async def test_health(client, host: str) -> dict:
    """Test health endpoint."""
    import httpx

    times = []
    errors = 0
    for _ in range(10):
        t0 = time.monotonic()
        try:
            resp = await client.get(f"{host}/api/health")
            elapsed = (time.monotonic() - t0) * 1000
            times.append(elapsed)
            if resp.status_code != 200:
                errors += 1
        except Exception:
            errors += 1
            times.append((time.monotonic() - t0) * 1000)

    return {
        "endpoint": "GET /api/health",
        "requests": 10,
        "errors": errors,
        "p50_ms": round(statistics.median(times), 1) if times else 0,
        "p95_ms": round(sorted(times)[int(len(times) * 0.95)] if times else 0, 1),
        "p99_ms": round(sorted(times)[-1] if times else 0, 1),
        "avg_ms": round(statistics.mean(times), 1) if times else 0,
    }


async def test_conversation_chat(client, host: str) -> dict:
    """Test conversation endpoint with chat intent."""
    import httpx

    payload = {
        "message": "Hello, what can you help me with?",
        "language": "en",
        "teacherId": "test-teacher-001",
    }

    times = []
    errors = 0
    for _ in range(3):
        t0 = time.monotonic()
        try:
            resp = await client.post(
                f"{host}/api/conversation",
                json=payload,
                timeout=30,
            )
            elapsed = (time.monotonic() - t0) * 1000
            times.append(elapsed)
            if resp.status_code != 200:
                errors += 1
                print(f"  [WARN] Chat returned {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            errors += 1
            times.append((time.monotonic() - t0) * 1000)
            print(f"  [ERROR] Chat failed: {e}")

    return {
        "endpoint": "POST /api/conversation (chat)",
        "requests": 3,
        "errors": errors,
        "p50_ms": round(statistics.median(times), 1) if times else 0,
        "p95_ms": round(sorted(times)[int(len(times) * 0.95)] if times else 0, 1),
        "p99_ms": round(sorted(times)[-1] if times else 0, 1),
        "avg_ms": round(statistics.mean(times), 1) if times else 0,
    }


async def test_workflow_generate(client, host: str) -> dict:
    """Test workflow generation endpoint."""
    import httpx

    payload = {
        "userPrompt": "Show me grade analysis for my class",
        "language": "en",
        "teacherId": "test-teacher-001",
    }

    times = []
    errors = 0
    for _ in range(2):
        t0 = time.monotonic()
        try:
            resp = await client.post(
                f"{host}/api/workflow/generate",
                json=payload,
                timeout=60,
            )
            elapsed = (time.monotonic() - t0) * 1000
            times.append(elapsed)
            if resp.status_code != 200:
                errors += 1
                print(f"  [WARN] Workflow returned {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            errors += 1
            times.append((time.monotonic() - t0) * 1000)
            print(f"  [ERROR] Workflow failed: {e}")

    return {
        "endpoint": "POST /api/workflow/generate",
        "requests": 2,
        "errors": errors,
        "p50_ms": round(statistics.median(times), 1) if times else 0,
        "p95_ms": round(sorted(times)[int(len(times) * 0.95)] if times else 0, 1),
        "p99_ms": round(sorted(times)[-1] if times else 0, 1),
        "avg_ms": round(statistics.mean(times), 1) if times else 0,
    }


async def test_conversation_stream(client, host: str) -> dict:
    """Test SSE streaming conversation endpoint."""
    import httpx

    payload = {
        "message": "Hello, tell me about your features",
        "language": "en",
        "teacherId": "test-teacher-001",
    }

    t0 = time.monotonic()
    ttfe = None
    event_count = 0
    has_error = False

    try:
        async with client.stream(
            "POST",
            f"{host}/api/conversation/stream",
            json=payload,
            timeout=60,
        ) as resp:
            if resp.status_code != 200:
                return {
                    "endpoint": "POST /api/conversation/stream (chat SSE)",
                    "requests": 1,
                    "errors": 1,
                    "note": f"Status {resp.status_code}",
                }

            async for line in resp.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                event_count += 1
                if ttfe is None:
                    ttfe = (time.monotonic() - t0) * 1000

    except Exception as e:
        has_error = True
        print(f"  [ERROR] Stream failed: {e}")

    duration = (time.monotonic() - t0) * 1000

    return {
        "endpoint": "POST /api/conversation/stream (chat SSE)",
        "requests": 1,
        "errors": 1 if has_error else 0,
        "ttfe_ms": round(ttfe, 1) if ttfe else None,
        "duration_ms": round(duration, 1),
        "event_count": event_count,
    }


async def test_concurrent_health(client, host: str, concurrency: int = 20) -> dict:
    """Stress test health endpoint with concurrent requests."""
    import httpx

    async def single_request():
        t0 = time.monotonic()
        try:
            resp = await client.get(f"{host}/api/health")
            return (time.monotonic() - t0) * 1000, resp.status_code == 200
        except Exception:
            return (time.monotonic() - t0) * 1000, False

    results = await asyncio.gather(*[single_request() for _ in range(concurrency)])
    times = [r[0] for r in results]
    errors = sum(1 for r in results if not r[1])

    return {
        "endpoint": f"GET /api/health x{concurrency} concurrent",
        "requests": concurrency,
        "errors": errors,
        "p50_ms": round(statistics.median(times), 1),
        "p95_ms": round(sorted(times)[int(len(times) * 0.95)], 1),
        "p99_ms": round(sorted(times)[-1], 1),
        "avg_ms": round(statistics.mean(times), 1),
        "max_ms": round(max(times), 1),
    }


async def main(host: str):
    import httpx

    print(f"\n{'='*60}")
    print(f"  Insight AI Agent — Baseline Performance Test")
    print(f"  Target: {host}")
    print(f"{'='*60}\n")

    async with httpx.AsyncClient(verify=False) as client:
        # 1. Health check
        print("[1/5] Testing health endpoint (10 sequential requests)...")
        r1 = await test_health(client, host)
        _print_result(r1)

        # 2. Concurrent health
        print("\n[2/5] Testing health endpoint (20 concurrent requests)...")
        r2 = await test_concurrent_health(client, host)
        _print_result(r2)

        # 3. Chat conversation
        print("\n[3/5] Testing conversation/chat (3 sequential requests)...")
        r3 = await test_conversation_chat(client, host)
        _print_result(r3)

        # 4. Workflow generation
        print("\n[4/5] Testing workflow/generate (2 sequential requests)...")
        r4 = await test_workflow_generate(client, host)
        _print_result(r4)

        # 5. SSE Stream
        print("\n[5/5] Testing conversation/stream SSE (1 request)...")
        r5 = await test_conversation_stream(client, host)
        _print_result(r5)

    # Summary
    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    results = [r1, r2, r3, r4, r5]
    total_errors = sum(r.get("errors", 0) for r in results)
    total_requests = sum(r.get("requests", 0) for r in results)
    print(f"  Total requests: {total_requests}")
    print(f"  Total errors:   {total_errors}")
    print(f"  Error rate:     {total_errors/total_requests*100:.1f}%")

    if total_errors == 0:
        print("\n  ✓ All tests passed — service is ready for load testing")
    else:
        print(f"\n  ✗ {total_errors} error(s) detected — fix before load testing")

    return 0 if total_errors == 0 else 1


def _print_result(result: dict):
    for k, v in result.items():
        if k == "endpoint":
            print(f"  Endpoint: {v}")
        elif isinstance(v, float):
            print(f"    {k}: {v:.1f}")
        else:
            print(f"    {k}: {v}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Baseline performance test")
    parser.add_argument("--host", default="http://localhost:5000", help="Service URL")
    args = parser.parse_args()

    exit_code = asyncio.run(main(args.host))
    sys.exit(exit_code)
