"""The score, recomputed from what is on disk and nothing else.

`feat-005`'s verification is that the aggregate **reproduces from the stored
per-task records alone**. So this module reads exactly two things —
`runs/<id>/manifest.json` for the denominator and `runs/<id>/records/*.json` for
the per-task results — and nothing in memory, nothing from the run that produced
them, and nothing from `results.tsv`. Run it twice, or run it a month later
against the same directory, and it must produce the same figure. `--check`
re-derives it and fails on any drift.

**Two costs, two columns, never one number.** They are not the same kind of
quantity and adding them would invent precision that neither has:

  agent  glm-4.6 on a z.ai **Coding Plan** key. z.ai publishes no rate for this
         plan, so the cost is **tokens, full stop** — no dollar figure and no
         estimate (AGENTS.md, "what this project measures"; DECISIONS entry 6).
  judge  gpt-4.1 on OpenAI, which **does** publish a rate. Cost is the published
         rate times the measured `usage` tokens, and the rate carries the date
         it was retrieved (`judge.PRICE_SOURCE`).

**A pass is the first terminal attempt's reward, not the best one.** Entry 7:
retries exist to survive provider errors and interruptions, never to re-roll a
task until it passes. One terminal record per task is written, and it is written
from the attempt that terminated first, so reading the records *is* reading the
first terminal attempt.

**"Judged" and "not judged" are counted apart.** A task whose agent never sent a
message gets `reward = 0.0` from a path where agisdk's `evaluate()` never ran
(see `judge.py`). That is a real failure and it counts as one — but it is not a
grade the judge gave, and `judge_calls` on the record is what tells the two
apart. The summary reports both so a judged score can never be quoted over
tasks that were never judged.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from web_agent_eval import judge, records

SCORE_NAME = "score.json"

#: Bumped when the aggregation's meaning changes, so a stale `score.json` from
#: an older definition is a mismatch rather than a silent comparison.
SCHEMA = 1


def _task_row(task_id: str, record: dict | None) -> dict:
    """One task's line: what it scored, what it cost, and whether it was judged."""
    if record is None:
        return {
            "task_id": task_id,
            "site": None,
            "status": "pending",
            "terminal": False,
            "passed": None,
            "reward": None,
            "steps": None,
            "agent_tokens": None,
            "wall_clock_s": None,
            "cap": None,
            "needs_judge": None,
            "judge_calls": 0,
            "judge_evaluate_calls": 0,
            "judge_prompt_tokens": 0,
            "judge_completion_tokens": 0,
            "judge_cached_tokens": 0,
            "judge_host": None,
            "judge_model": None,
        }
    ledger = record.get("judge") or {}
    tokens = ledger.get("tokens") or {}
    calls = ledger.get("calls") or []
    status = record.get("status")
    return {
        "task_id": task_id,
        "site": record.get("site"),
        "status": status,
        "terminal": records.is_terminal(status or ""),
        "passed": status == records.PASSED,
        "reward": record.get("reward"),
        "steps": record.get("steps"),
        "agent_tokens": record.get("tokens"),
        "wall_clock_s": record.get("wall_clock_s"),
        "cap": record.get("cap"),
        "needs_judge": record.get("needs_judge"),
        "judge_calls": len(calls),
        "judge_evaluate_calls": ledger.get("evaluate_calls", 0),
        "judge_prompt_tokens": tokens.get("prompt", 0),
        "judge_completion_tokens": tokens.get("completion", 0),
        "judge_cached_tokens": tokens.get("cached_prompt", 0),
        # Taken from the calls themselves, not from the endpoint assertion: this
        # is where the request really went, as reported by the client that made
        # it. Distinct values would mean one run judged against two providers.
        "judge_host": sorted({c.get("host") for c in calls if c.get("host")}) or None,
        "judge_model": sorted({c.get("served_model") for c in calls if c.get("served_model")})
        or None,
    }


def _stats(values: list) -> dict:
    clean = [v for v in values if isinstance(v, int | float)]
    if not clean:
        return {"n": 0, "total": 0, "mean": None, "min": None, "max": None}
    return {
        "n": len(clean),
        "total": round(sum(clean), 3),
        "mean": round(sum(clean) / len(clean), 3),
        "min": round(min(clean), 3),
        "max": round(max(clean), 3),
    }


def score(run_dir: Path | str) -> dict:
    """The whole aggregate, from `manifest.json` and `records/` alone."""
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    stored = records.terminal_records(run_dir)

    rows = [_task_row(task_id, stored.get(task_id)) for task_id in manifest["task_ids"]]
    terminal = [r for r in rows if r["terminal"]]
    passed = [r for r in terminal if r["passed"]]

    judged = [r for r in terminal if r["judge_calls"] > 0]
    needed_judge = [r for r in terminal if r["needs_judge"]]
    # A task that needed the judge, terminated, and was never judged: the agent
    # never answered, so agisdk's evaluate() never ran. A real zero, but not a
    # graded one, and it is reported rather than folded into the rate silently.
    unjudged = [r for r in needed_judge if r["judge_calls"] == 0]

    judge_prompt = sum(r["judge_prompt_tokens"] for r in terminal)
    judge_completion = sum(r["judge_completion_tokens"] for r in terminal)
    judge_cached = sum(r["judge_cached_tokens"] for r in terminal)
    hosts = sorted({h for r in terminal for h in (r["judge_host"] or [])})
    models = sorted({m for r in terminal for m in (r["judge_model"] or [])})

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1

    payload = {
        "schema": SCHEMA,
        "run_id": manifest["run_id"],
        "population": manifest["population"],
        "manifest_n": len(manifest["task_ids"]),
        "model": manifest["model"],
        "caps": manifest["caps"],
        "counts": counts,
        "terminal": len(terminal),
        "pending": [r["task_id"] for r in rows if not r["terminal"]],
        "passed": len(passed),
        # Stated over what has actually been scored. `manifest_n` is the
        # denominator a published rate must use, and it is not this one until
        # every task is terminal.
        "rate_over_terminal": round(len(passed) / len(terminal), 6) if terminal else None,
        "rate_over_manifest": (
            round(len(passed) / len(manifest["task_ids"]), 6)
            if terminal and len(terminal) == len(manifest["task_ids"])
            else None
        ),
        "agent": {
            "provider": "z.ai Coding Plan",
            "model": manifest["model"],
            "rate_published": False,
            "usd": None,
            "usd_note": "z.ai publishes no rate for this Coding Plan key, so agent cost is "
                        "reported in tokens and no dollar figure is given "
                        "(AGENTS.md; DECISIONS entry 6). Never summed with the judge column.",
            "tokens": _stats([r["agent_tokens"] for r in terminal]),
        },
        "judge": {
            "provider": "OpenAI",
            "model": judge.default_judge_model(),
            "models_served": models,
            "hosts": hosts,
            "rate_published": True,
            "rate_usd_per_1m": dict(judge.GPT_41_USD_PER_1M),
            "rate_source": judge.PRICE_SOURCE,
            "tasks_needing_judge": len(needed_judge),
            "tasks_judged": len(judged),
            "tasks_unjudged": [r["task_id"] for r in unjudged],
            "calls": sum(r["judge_calls"] for r in terminal),
            "tokens": {
                "prompt": judge_prompt,
                "completion": judge_completion,
                "cached_prompt": judge_cached,
                "total": judge_prompt + judge_completion,
            },
            "usd": round(judge.usd(judge_prompt, judge_completion, judge_cached), 6),
        },
        "wall_clock_s": _stats([r["wall_clock_s"] for r in terminal]),
        "steps": _stats([r["steps"] for r in terminal]),
        "tasks": rows,
    }
    payload["digest"] = digest(payload)
    return payload


def digest(payload: dict) -> str:
    """A stable fingerprint of everything the aggregation claims.

    `--check` compares this rather than eyeballing a rate: a drift anywhere in
    the per-task rows shows up even when the headline number happens to match.
    """
    body = {k: v for k, v in payload.items() if k != "digest"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def score_path(run_dir: Path | str) -> Path:
    return Path(run_dir) / SCORE_NAME


def write(run_dir: Path | str, payload: dict) -> Path:
    path = score_path(run_dir)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    return path


def subset_rates(payload: dict) -> dict:
    """The rate split by how the task is scored: `jmespath` checks vs the judge.

    Derived from the same rows the headline is, so it adds nothing to the
    aggregation's meaning and does not enter the digest. It is reported because
    the two subsets are **different task shapes** (entry 10): `jmespath` evals
    check state mutations — did the email get marked read — and `llm_boolean`
    evals check answer text. Publishing only the combined rate hides which of
    the two the agent is actually failing, and publishing only the `jmespath`
    half is the n=47 shortcut entry 10 rejected. A reader gets both.
    """
    out = {}
    for label, want in (("judge (llm_boolean)", True), ("jmespath only", False)):
        rows = [r for r in payload["tasks"] if r["needs_judge"] is want]
        terminal = [r for r in rows if r["terminal"]]
        passed = [r for r in terminal if r["passed"]]
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        out[label] = {
            "n": len(rows),
            "terminal": len(terminal),
            "passed": len(passed),
            "counts": counts,
            "rate_over_terminal": (
                round(len(passed) / len(terminal), 6) if terminal else None
            ),
        }
    return out


def subsets(payload: dict) -> str:
    lines = ["by eval type — different task shapes, so both are stated (entry 10):"]
    for label, data in subset_rates(payload).items():
        rate = ("n/a" if data["rate_over_terminal"] is None
                else f"{data['rate_over_terminal']:.1%}")
        lines.append(
            f"  {label:22s} passed {data['passed']}/{data['terminal']} terminal "
            f"of n={data['n']}  ({rate})  "
            f"{json.dumps(data['counts'], sort_keys=True)}"
        )
    return "\n".join(lines)


def render(payload: dict) -> str:
    """The human-readable version. Two cost columns, never added together."""
    lines: list[str] = []
    a = payload["agent"]
    j = payload["judge"]
    lines.append(
        f"run {payload['run_id']}: population {payload['population']} "
        f"(manifest n={payload['manifest_n']}), model {payload['model']}"
    )
    lines.append(
        f"terminal {payload['terminal']}/{payload['manifest_n']}, "
        f"passed {payload['passed']}, "
        f"rate over terminal "
        + (f"{payload['rate_over_terminal']:.3f}" if payload["rate_over_terminal"] is not None
           else "n/a")
        + (f", rate over manifest {payload['rate_over_manifest']:.3f}"
           if payload["rate_over_manifest"] is not None else "")
    )
    lines.append(f"counts: {json.dumps(payload['counts'], sort_keys=True)}")
    lines.append("")
    lines.append(subsets(payload))
    lines.append("")
    header = (f"{'task':22s} {'status':9s} {'pass':5s} {'steps':>5s} {'agent tok':>10s} "
              f"{'jcalls':>6s} {'judge tok':>10s} {'judge $':>9s} {'secs':>7s}")
    lines.append(header)
    lines.append("-" * len(header))
    for row in payload["tasks"]:
        jt = row["judge_prompt_tokens"] + row["judge_completion_tokens"]
        cost = judge.usd(row["judge_prompt_tokens"], row["judge_completion_tokens"],
                         row["judge_cached_tokens"])
        secs = "-" if row["wall_clock_s"] is None else format(row["wall_clock_s"], ".1f")
        verdict = "-" if row["passed"] is None else ("yes" if row["passed"] else "no")
        lines.append(
            f"{row['task_id']:22s} {row['status']!s:9s} {verdict:5s} "
            f"{(row['steps'] if row['steps'] is not None else '-')!s:>5s} "
            f"{(row['agent_tokens'] if row['agent_tokens'] is not None else '-')!s:>10s} "
            f"{row['judge_calls']:>6d} {jt:>10d} {cost:>9.5f} {secs:>7s}"
        )
    lines.append("")
    lines.append("cost — two columns, deliberately not summed:")
    lines.append(
        f"  AGENT  {a['model']} on {a['provider']}: "
        f"{a['tokens']['total']} tokens over {a['tokens']['n']} tasks "
        f"(mean {a['tokens']['mean']}, min {a['tokens']['min']}, max {a['tokens']['max']}); "
        f"USD: none — {a['usd_note']}"
    )
    lines.append(
        f"  JUDGE  {j['model']} on {j['provider']}: {j['calls']} calls, "
        f"{j['tokens']['prompt']} prompt + {j['tokens']['completion']} completion tokens "
        f"= ${j['usd']:.6f} at {j['rate_usd_per_1m']['input']}/{j['rate_usd_per_1m']['output']} "
        f"USD per 1M in/out"
    )
    lines.append(f"         rate source: {j['rate_source']}")
    lines.append(
        f"         judged {j['tasks_judged']} of the {j['tasks_needing_judge']} terminal tasks "
        f"that carry an llm_boolean eval; hosts {j['hosts']}, served {j['models_served']}"
    )
    if j["tasks_unjudged"]:
        lines.append(
            f"         NOT judged (agent never answered, so agisdk's evaluate() never ran): "
            f"{', '.join(j['tasks_unjudged'])}"
        )
    lines.append(f"wall clock: {json.dumps(payload['wall_clock_s'])}")
    lines.append(f"digest: {payload['digest']}")
    return "\n".join(lines)
