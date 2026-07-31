"""Prove REAL's judge actually runs, against OpenAI, and returns a grade.

    uv run python scripts/judge_probe.py                      # endpoint assertion only
    uv run python scripts/judge_probe.py --task v1.dashdish-1 # one full episode
    uv run python scripts/judge_probe.py --control            # break it on purpose

`feat-005` cannot claim a judged score until this has run. Two failure modes
look exactly like success and both are checked here rather than assumed away:

  1. **The judge is never called and a score appears anyway.** agisdk's
     `validate()` only evaluates once the agent has sent a message, so an agent
     that never answers gets `reward = 0.0` without `evaluate()` ever running.
     The ledger counts `evaluate()` calls and judge calls separately, and a task
     with an `llm_boolean` eval that reports zero judge calls has not been
     graded — whatever its reward says.

  2. **`OPENAI_BASE_URL` leaks and the judge runs on z.ai.** `OpenAI()` takes no
     arguments in agisdk, so it reads that variable from the environment. The
     assertion below reports the base URL the client really resolved, and the
     per-call records report the base URL of the client that really made the
     call — not the one this script hoped for.

`--control` is the check on the check: it sets `OPENAI_BASE_URL` to z.ai and
confirms the assertion refuses. A gate that has never been seen to fail is not
evidence that it works (AGENTS.md).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from web_agent_eval import judge
from web_agent_eval.caps import Caps


def show_endpoint() -> dict:
    print("=== judge endpoint assertion ===")
    info = judge.require()
    for key in ("OPENAI_BASE_URL_env", "OPENAI_API_KEY_set", "OPENAI_API_KEY_prefix",
                "base_url", "host", "is_openai", "model_default"):
        print(f"  {key:22s} = {info[key]!r}")
    assert info["host"] == judge.OPENAI_HOST, info
    assert info["is_openai"] is True, info
    assert info["model_default"] == "gpt-4.1", info
    print(f"  ASSERTED: host is {judge.OPENAI_HOST} and the judge model default is "
          f"{info['model_default']}")
    print(f"  rate: {judge.GPT_41_USD_PER_1M} USD per 1M tokens")
    print(f"  rate source: {judge.PRICE_SOURCE}")
    return info


def control() -> int:
    """Set OPENAI_BASE_URL to z.ai and confirm the assertion refuses."""
    print("=== control: OPENAI_BASE_URL leaked to z.ai ===")
    os.environ["OPENAI_BASE_URL"] = "https://api.z.ai/api/coding/paas/v4/"
    try:
        info = judge.require()
    except judge.JudgeMisrouted as exc:
        print(f"  refused, as it must: {exc}")
        print("  CONTROL PASSED — the assertion is not vacuous")
        return 0
    finally:
        os.environ.pop("OPENAI_BASE_URL", None)
    print(f"  CONTROL FAILED — require() accepted a misrouted judge: {info}", file=sys.stderr)
    return 1


def run_task(task_id: str, *, level: str, caps: Caps, out_dir: Path) -> int:
    """One task, in this process — and only ever one.

    Measured while building this probe, and it is a second, independent reason
    for entry 12's one-process-per-task rule. That rule was justified by state
    contamination from an abandoned worker thread; this is a hard technical
    limit that bites even when nothing was abandoned. agisdk starts Playwright's
    **sync** driver once per process and caches it, and the driver's greenlet
    dispatcher is bound to the thread that started it. Every episode gets a
    fresh `BoundedRunner` thread, so a second episode in the same process meets
    a dispatcher belonging to the first episode's now-exited thread:

        greenlet.error: cannot switch to a different thread (which happens to
        have exited)                        — at env.reset -> pw.chromium.launch

    zero steps, zero tokens, `errored`. So the probe refuses a second task
    rather than reporting a fake failure, and `batch.py` was already right.
    """
    from web_agent_eval import batch

    needs = judge.task_needs_judge(task_id)
    print(f"\n=== episode: {task_id} ===")
    print(f"  has an llm_boolean eval: {needs}")
    out_dir.mkdir(parents=True, exist_ok=True)
    record = batch.real_episode(
        task_id, caps=caps, output_path=out_dir / f"{task_id}.json", level=level
    )
    ledger = record["judge"]
    print(f"  outcome={record['outcome']} reward={record['reward']} "
          f"steps={record['steps']} agent_tokens={record['tokens']['charged']} "
          f"{record['elapsed_s']:.1f}s")
    print(f"  agisdk evaluate() calls: {ledger['evaluate_calls']}")
    print(f"  judge model calls:       {ledger['judge_calls']}")
    for call in ledger["calls"]:
        print(f"    -> base_url={call['base_url']!r} host={call['host']!r}")
        print(f"       requested={call['requested_model']!r} served={call['served_model']!r}")
        print(f"       usage: prompt={call['prompt_tokens']} "
              f"completion={call['completion_tokens']} total={call['total_tokens']} "
              f"cached={call['cached_tokens']}  {call['latency_s']:.2f}s")
        print(f"       reply: {call['reply']!r}")
        cost = judge.usd(call["prompt_tokens"], call["completion_tokens"], call["cached_tokens"])
        print(f"       cost at the published rate: ${cost:.6f}")
    for ev in ledger["llm_evals"]:
        print(f"    grade: similarity={ev['similarity']} is_correct={ev['is_correct']}")
        print(f"       rubric: {ev['rubric'][:160]}")
        print(f"       answer: {ev['model_response'][:160]!r}")

    if needs:
        if ledger["judge_calls"] == 0:
            print("\n  NOT PROVEN: this task needs the judge and the judge was never called. "
                  "The agent did not send a message, so agisdk's validate() short-circuited "
                  "and evaluate() never ran. reward=0.0 here is real but UNGRADED.",
                  file=sys.stderr)
            return 1
        hosts = {c["host"] for c in ledger["calls"]}
        requested = {c["requested_model"] for c in ledger["calls"]}
        served = {c["served_model"] for c in ledger["calls"]}
        assert hosts == {judge.OPENAI_HOST}, f"judge calls went to {hosts}"
        assert requested == {"gpt-4.1"}, f"judge requested {requested}"
        # OpenAI answers the `gpt-4.1` alias with a dated snapshot —
        # `gpt-4.1-2025-04-14` — and says so in the response's `model` field.
        # That is the opposite of entry 9's z.ai finding, where `glm-5.1` was
        # answered by `glm-5.2` with no way to pin it: here the alias resolves to
        # something pinnable and the server names it. What is recorded is the
        # served string, so a rerun that gets a different snapshot is visible.
        assert all(m and m.startswith("gpt-4.1") for m in served), f"judge served {served}"
        assert any(e["similarity"] is not None for e in ledger["llm_evals"]), ledger["llm_evals"]
        print(f"\n  PROVEN: {ledger['judge_calls']} judge call(s) to {hosts}, "
              f"requested {requested}, served {served}, returning a numeric grade.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", action="append", default=[],
                        help="ONE task id to run end to end; a second one is refused, "
                             "see the note in run_task()")
    parser.add_argument("--control", action="store_true",
                        help="only run the misrouted-judge control")
    parser.add_argument("--level", default="lean")
    parser.add_argument("--max-steps", type=int, default=25)
    parser.add_argument("--max-wall-clock-s", type=float, default=300.0)
    parser.add_argument("--out", default="runs/judgeproof")
    args = parser.parse_args(argv)

    if args.control:
        return control()

    show_endpoint()
    print(json.dumps({"note": "the assertion above is the one that must hold before any "
                              "judged number is published"}))

    if len(args.task) > 1:
        print("one task per invocation — a second episode in this process cannot start "
              "Playwright (see run_task's docstring, and DECISIONS entry 12). Invoke the "
              "probe again for the next task.", file=sys.stderr)
        return 1
    caps = Caps(max_steps=args.max_steps, max_wall_clock_s=args.max_wall_clock_s)
    status = 0
    for task_id in args.task:
        status |= run_task(task_id, level=args.level, caps=caps, out_dir=Path(args.out))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
