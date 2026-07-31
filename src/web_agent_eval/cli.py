"""Shared argument handling for `scripts/run_batch.py` and `scripts/supervise.py`.

Both take the same run definition, and they must agree on it exactly: the
manifest is frozen, so a supervisor that spelled the run differently from the
runner it invokes would be refused by `manifest.ensure` mid-flight. Keeping the
parser in one place is what makes "identical invocation resumes identically"
true rather than hoped for.
"""

from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime
from pathlib import Path

from web_agent_eval import glm
from web_agent_eval import manifest as manifest_module
from web_agent_eval.batch import Budget
from web_agent_eval.caps import (
    DEFAULT_MAX_STEPS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MAX_WALL_CLOCK_S,
)

DEFAULT_ENTRYPOINT = "web_agent_eval.batch:real_episode"

#: Entry 7: z.ai publishes 3 for glm-4.6, and `feat-004` fixes that as the
#: default. The measured ceiling on this key is recorded in DECISIONS; the
#: default stays where the decision put it, because raising it is a scoping
#: decision and not something a runner should do to itself.
DEFAULT_CONCURRENCY = 3


def add_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", required=True, help="names runs/<run-id>/")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument(
        "--population", default="47", choices=manifest_module.POPULATIONS,
        help="112 = the full v1 set; 102 = reachable; 47 = reachable and scorable "
             "with z.ai's key alone; explicit = exactly --tasks (DECISIONS entry 5)",
    )
    parser.add_argument("--tasks", default="",
                        help="comma-separated task ids, for --population explicit")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--level", default="lean", help="observation richness (feat-002)")
    parser.add_argument("--entrypoint", default=DEFAULT_ENTRYPOINT,
                        help="module:function run in each worker process")
    parser.add_argument("--model", default=glm.DEFAULT_MODEL)
    parser.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--max-wall-clock-s", type=float, default=DEFAULT_MAX_WALL_CLOCK_S)
    parser.add_argument("--budget-tokens", type=int, default=None,
                        help="run-level token budget; exceeding it exits 2")
    parser.add_argument("--budget-wall-clock-s", type=float, default=None,
                        help="run-level wall-clock budget, measured from the manifest's "
                             "creation so it spans restarts; exceeding it exits 2")
    parser.add_argument("--note", default="")


def run_dir_for(args) -> Path:
    return Path(args.runs_dir) / args.run_id


def manifest_for(args) -> manifest_module.Manifest:
    """The manifest this invocation is asking for, before it meets any on disk.

    Task ids are checked against REAL's installed v1 set whenever the run drives
    real episodes, so a typo fails before the first browser starts. A run
    pointed at another entrypoint — `feat-004`'s own tests, which run fake
    episodes whose ids encode how they misbehave — is exempt from that check and
    says so in its manifest.
    """
    return manifest_module.build(
        args.run_id,
        population_name=args.population,
        explicit=[t.strip() for t in args.tasks.split(",") if t.strip()],
        concurrency=args.concurrency,
        caps={
            "max_steps": args.max_steps,
            "max_tokens": args.max_tokens,
            "max_wall_clock_s": args.max_wall_clock_s,
        },
        model=args.model,
        base_url=glm.base_url(),
        episode_entrypoint=args.entrypoint,
        level=args.level,
        note=args.note or f"concurrency {args.concurrency}, level {args.level}; "
                          f"per-task wall clock at N>1 is not comparable to sequential "
                          f"(DECISIONS entry 7)",
        real_tasks=args.entrypoint == DEFAULT_ENTRYPOINT,
    )


def level_for(args, manifest: manifest_module.Manifest) -> str:
    """The richness the round must run at: the manifest's, not the flag's.

    `feat-007` is a comparison between two runs that differ in exactly this, so
    the level a round runs at has to come from the frozen record rather than
    from whatever was typed. `manifest.ensure` already refuses an invocation
    that contradicts a stored level, which leaves one case: a manifest written
    before the field existed. Then there is nothing to obey and the flag stands
    — which is what those runs did anyway.
    """
    return manifest.level or args.level


def budget_for(args) -> Budget:
    return Budget(tokens=args.budget_tokens, wall_clock_s=args.budget_wall_clock_s)


def run_started_monotonic(manifest: manifest_module.Manifest) -> float:
    """The monotonic instant this *run* began — its manifest's creation.

    Not the instant this process began. A wall-clock budget for a run that
    resumes after a kill has to be measured from when the run started, or an
    interrupted eight-hour run gets a fresh eight hours every restart.
    """
    created = datetime.fromisoformat(manifest.created)
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    elapsed = (datetime.now(UTC) - created).total_seconds()
    return time.monotonic() - max(elapsed, 0.0)


def forwarded_args(args) -> list[str]:
    """The same run definition, as flags — what the supervisor hands the runner."""
    out = [
        "--run-id", args.run_id,
        "--runs-dir", str(args.runs_dir),
        "--population", args.population,
        "--level", args.level,
        "--entrypoint", args.entrypoint,
        "--model", args.model,
        "--max-steps", str(args.max_steps),
        "--max-tokens", str(args.max_tokens),
        "--max-wall-clock-s", str(args.max_wall_clock_s),
    ]
    if args.tasks:
        out += ["--tasks", args.tasks]
    if args.note:
        out += ["--note", args.note]
    if args.budget_tokens is not None:
        out += ["--budget-tokens", str(args.budget_tokens)]
    if args.budget_wall_clock_s is not None:
        out += ["--budget-wall-clock-s", str(args.budget_wall_clock_s)]
    return out
