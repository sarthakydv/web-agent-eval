"""Measure what this key actually allows concurrently, and what it allows for hours.

docs/DECISIONS.md entry 7 caps concurrency at 3 because z.ai *publishes* 3 for
`glm-4.6` — but that figure is for the pay-as-you-go API and this key is a
Coding Plan key, and entry 4 proved those are different products (the same key
gets 429 on `paas/v4` and 200 on `coding/paas/v4`). So the 3 is an assumption
until it is measured, and this script measures it two ways:

  BURST      fire N simultaneous trivial completions, N = 2..5, and record which
             are rejected and with what code. This finds the instantaneous
             ceiling.

  SUSTAINED  hold N workers issuing paced trivial completions for a long window
             and bucket the results by minute. This finds the other thing, the
             one a burst cannot see: **a quota that only appears two hours into
             a run.** A ceiling that holds for ten seconds and collapses at hour
             two is the failure that costs a whole unattended night, and
             `feat-006` runs unattended for hours.

The sustained phase is paced rather than flat out on purpose. An episode is
model-bound at roughly one call every 4 s per worker (entry 4: 9 calls in
35.4 s), so a paced probe reproduces the load `feat-006` will actually apply.
Firing as fast as the socket allows would measure a load this project never
generates and would burn plan quota to do it.

Usage:
    uv run python scripts/concurrency_probe.py                 # burst only
    uv run python scripts/concurrency_probe.py --sustained-minutes 40
    uv run python scripts/concurrency_probe.py --sustained-only --concurrency 3
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from web_agent_eval import glm

PROMPT = "Reply with exactly: ok"
MAX_TOKENS = 16


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def one_call(client, model: str) -> dict:
    """One trivial completion. Returns what happened, never raises."""
    started = time.monotonic()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": PROMPT}],
            max_tokens=MAX_TOKENS,
            temperature=0.0,
            extra_body={"thinking": {"type": "disabled"}},
            timeout=60.0,
        )
        return {
            "ok": True,
            "status": 200,
            "latency_s": time.monotonic() - started,
            "tokens": getattr(response.usage, "total_tokens", 0) or 0,
            "served_model": response.model,
        }
    except Exception as exc:  # noqa: BLE001 — a rejection is the measurement
        status = getattr(exc, "status_code", None)
        body = getattr(exc, "body", None)
        code = None
        message = str(exc)
        if isinstance(body, dict):
            err = body.get("error") or {}
            code = err.get("code")
            message = err.get("message", message)
        return {
            "ok": False,
            "status": status,
            "provider_code": code,
            "error_type": type(exc).__name__,
            "message": message[:200],
            "latency_s": time.monotonic() - started,
        }


# --------------------------------------------------------------------------
# burst: the instantaneous ceiling
# --------------------------------------------------------------------------


def burst(model: str, n: int) -> list[dict]:
    """Fire `n` completions that genuinely start at the same instant.

    A barrier, not a thread pool: a pool would let the first request finish
    before the last one starts, which measures nothing about concurrency.
    """
    client_per_thread = [glm.make_client() for _ in range(n)]
    barrier = threading.Barrier(n)
    results: list[dict | None] = [None] * n

    def worker(i: int) -> None:
        barrier.wait()
        results[i] = one_call(client_per_thread[i], model)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return [r for r in results if r is not None]


def run_burst(model: str, levels: list[int], settle_s: float) -> dict:
    print(f"\n=== BURST — simultaneous trivial completions, {model} ===\n")
    print(f"{'N':>3}  {'accepted':>8}  {'rejected':>8}  {'codes':<28} "
          f"{'latency min/max (s)':>22}")
    print("-" * 78)
    phase: dict = {"levels": []}
    for n in levels:
        results = burst(model, n)
        accepted = [r for r in results if r["ok"]]
        rejected = [r for r in results if not r["ok"]]
        codes = Counter(
            f"{r.get('status')}/{r.get('provider_code')}" for r in rejected
        )
        latencies = [r["latency_s"] for r in results]
        print(f"{n:>3}  {len(accepted):>8}  {len(rejected):>8}  "
              f"{(', '.join(f'{k} x{v}' for k, v in codes.items()) or '-'):<28} "
              f"{min(latencies):>10.2f} /{max(latencies):>9.2f}")
        phase["levels"].append({
            "n": n,
            "accepted": len(accepted),
            "rejected": len(rejected),
            "codes": dict(codes),
            "latency_min_s": min(latencies),
            "latency_max_s": max(latencies),
            "results": results,
        })
        # Let the provider's window clear before the next level, or level N+1
        # measures level N's tail.
        time.sleep(settle_s)
    return phase


# --------------------------------------------------------------------------
# sustained: the quota that only shows up later
# --------------------------------------------------------------------------


def run_sustained(model: str, n: int, minutes: float, interval_s: float) -> dict:
    """Hold `n` paced workers for `minutes`, bucketed by minute."""
    print(f"\n=== SUSTAINED — {n} workers, one call each per {interval_s:g}s, "
          f"{minutes:g} min ===\n")
    deadline = time.monotonic() + minutes * 60
    started_at = time.monotonic()
    lock = threading.Lock()
    calls: list[dict] = []

    def worker(i: int) -> None:
        client = glm.make_client()
        while time.monotonic() < deadline:
            cycle_start = time.monotonic()
            result = one_call(client, model)
            result["worker"] = i
            result["minute"] = int((cycle_start - started_at) // 60)
            result["t_s"] = cycle_start - started_at
            with lock:
                calls.append(result)
            nap = interval_s - (time.monotonic() - cycle_start)
            if nap > 0:
                time.sleep(nap)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()

    # Progress every minute, so a long probe is watchable rather than silent.
    reported = -1
    while any(t.is_alive() for t in threads):
        time.sleep(2)
        minute = int((time.monotonic() - started_at) // 60)
        if minute > reported:
            reported = minute
            with lock:
                done = list(calls)
            ok = sum(1 for c in done if c["ok"])
            print(f"  [{now()}] minute {minute:>3}: {len(done):>5} calls, "
                  f"{ok:>5} ok, {len(done) - ok:>3} rejected", flush=True)
    for t in threads:
        t.join()

    by_minute: dict[int, list[dict]] = {}
    for c in calls:
        by_minute.setdefault(c["minute"], []).append(c)

    print(f"\n{'minute':>7}  {'calls':>6}  {'ok':>5}  {'rejected':>8}  "
          f"{'codes':<20}  {'mean latency (s)':>17}  {'tokens':>7}")
    print("-" * 78)
    buckets = []
    for minute in sorted(by_minute):
        rows = by_minute[minute]
        ok = [r for r in rows if r["ok"]]
        bad = [r for r in rows if not r["ok"]]
        codes = Counter(f"{r.get('status')}/{r.get('provider_code')}" for r in bad)
        mean_latency = sum(r["latency_s"] for r in ok) / max(len(ok), 1)
        tokens = sum(r.get("tokens", 0) for r in ok)
        print(f"{minute:>7}  {len(rows):>6}  {len(ok):>5}  {len(bad):>8}  "
              f"{(', '.join(f'{k} x{v}' for k, v in codes.items()) or '-'):<20}  "
              f"{mean_latency:>17.2f}  {tokens:>7}")
        buckets.append({
            "minute": minute,
            "calls": len(rows),
            "ok": len(ok),
            "rejected": len(bad),
            "codes": dict(codes),
            "mean_latency_s": mean_latency,
            "tokens": tokens,
        })

    ok_all = [c for c in calls if c["ok"]]
    bad_all = [c for c in calls if not c["ok"]]
    return {
        "concurrency": n,
        "minutes": minutes,
        "interval_s": interval_s,
        "calls": len(calls),
        "ok": len(ok_all),
        "rejected": len(bad_all),
        "codes": dict(Counter(
            f"{r.get('status')}/{r.get('provider_code')}" for r in bad_all
        )),
        "tokens": sum(c.get("tokens", 0) for c in ok_all),
        "first_minute_ok": buckets[0]["ok"] if buckets else 0,
        "last_minute_ok": buckets[-1]["ok"] if buckets else 0,
        "by_minute": buckets,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=glm.DEFAULT_MODEL)
    parser.add_argument("--levels", default="2,3,4,5",
                        help="burst sizes to fire, comma separated")
    parser.add_argument("--settle-s", type=float, default=5.0)
    parser.add_argument("--sustained-minutes", type=float, default=0.0,
                        help="0 skips the sustained phase")
    parser.add_argument("--concurrency", type=int, default=0,
                        help="workers in the sustained phase; default = the "
                             "largest burst level that was fully accepted")
    parser.add_argument("--interval-s", type=float, default=4.0,
                        help="seconds between a worker's calls; 4s is the "
                             "gate's measured episode cadence (entry 4)")
    parser.add_argument("--sustained-only", action="store_true")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    levels = [int(x) for x in args.levels.split(",") if x.strip()]
    report: dict = {
        "started": now(),
        "model": args.model,
        "base_url": glm.base_url(),
        "prompt": PROMPT,
        "max_tokens": MAX_TOKENS,
    }

    if not args.sustained_only:
        report["burst"] = run_burst(args.model, levels, args.settle_s)
        clean = [lv["n"] for lv in report["burst"]["levels"] if lv["rejected"] == 0]
        report["burst"]["max_fully_accepted"] = max(clean) if clean else 0

    if args.sustained_minutes > 0:
        n = args.concurrency or report.get("burst", {}).get("max_fully_accepted") or 3
        report["sustained"] = run_sustained(
            args.model, n, args.sustained_minutes, args.interval_s
        )

    report["finished"] = now()
    out = Path(args.out).resolve() if args.out else (
        ROOT / "runs" / "probe" / f"concurrency_{datetime.now(UTC).strftime('%Y-%m-%d_%H-%M-%S')}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nwritten: {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
