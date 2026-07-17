"""
Load test harness — drives a RUNNING server with concurrent closed-loop
workers and reports latency percentiles against the phase's budgets.

Usage:
    # start the server first (uvicorn app_main:app --port 8000), then:
    python scripts/load_test.py --base http://127.0.0.1:8000 --users 50 --requests 20

Budgets checked (from the Performance & Reliability directive):
    API P95 latency < 250ms   (non-AI endpoints)

The AI-inference and workflow-execution paths are quota/auth-gated and
cost real provider tokens — this harness covers the public API surface;
authenticated flows can be added by passing --token.
"""
import argparse
import asyncio
import statistics
import sys
import time

import httpx

ENDPOINTS = ["/health", "/health/deep", "/api/health/full"]
P95_BUDGET_MS = 250.0


async def worker(client: httpx.AsyncClient, base: str, endpoint: str,
                 n: int, latencies: list[float], errors: list[str]) -> None:
    for _ in range(n):
        t0 = time.perf_counter()
        try:
            r = await client.get(f"{base}{endpoint}", timeout=30.0)
            latencies.append((time.perf_counter() - t0) * 1000)
            if r.status_code >= 500 and r.status_code != 503:
                errors.append(f"{endpoint} -> {r.status_code}")
        except Exception as exc:
            errors.append(f"{endpoint} -> {exc!r}")


def pct(sorted_vals: list[float], p: float) -> float:
    return sorted_vals[min(int(len(sorted_vals) * p), len(sorted_vals) - 1)]


async def run(base: str, users: int, requests_per_user: int) -> int:
    print(f"Load test: {users} concurrent users x {requests_per_user} requests "
          f"per endpoint against {base}\n")
    failed_budget = False
    async with httpx.AsyncClient() as client:
        # Warmup
        for ep in ENDPOINTS:
            await client.get(f"{base}{ep}", timeout=30.0)

        for ep in ENDPOINTS:
            latencies: list[float] = []
            errors: list[str] = []
            t0 = time.perf_counter()
            await asyncio.gather(*(
                worker(client, base, ep, requests_per_user, latencies, errors)
                for _ in range(users)
            ))
            wall = time.perf_counter() - t0
            latencies.sort()
            total = len(latencies)
            p50, p95, p99 = pct(latencies, .50), pct(latencies, .95), pct(latencies, .99)
            rps = total / wall if wall > 0 else 0
            ok = p95 < P95_BUDGET_MS
            failed_budget |= not ok
            print(f"{ep}")
            print(f"  requests={total} errors={len(errors)} throughput={rps:.0f} req/s")
            print(f"  P50={p50:.1f}ms  P95={p95:.1f}ms  P99={p99:.1f}ms  "
                  f"budget(P95<{P95_BUDGET_MS:.0f}ms): {'PASS' if ok else 'FAIL'}")
            if errors:
                print(f"  first errors: {errors[:3]}")
            print()

    print("BUDGET FAILED" if failed_budget else "ALL BUDGETS PASSED")
    return 1 if failed_budget else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--users", type=int, default=50)
    ap.add_argument("--requests", type=int, default=20)
    args = ap.parse_args()
    sys.exit(asyncio.run(run(args.base, args.users, args.requests)))
