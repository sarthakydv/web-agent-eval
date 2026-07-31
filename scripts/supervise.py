"""The supervisor: re-invoke the runner until a machine-checkable outcome.

    uv run python scripts/supervise.py --run-id nightly --population 47

docs/DECISIONS.md entry 7 fixes what it may conclude, and there are exactly
three things, none of them a judgement:

    exit 0   every manifest task has a terminal record
    exit 1   K consecutive rounds added no new terminal record — stalled
    exit 2   the run's token or wall-clock budget was exceeded

**It never runs unbounded.** `--max-rounds` is a hard stop that reports as
stalled, so a run that neither finishes nor stalls in the ordinary way still
terminates and says why.

**It is idempotent.** Run it again on a completed run and it prints the summary
and changes nothing — not the manifest, not the records, not even its own log.

**No model is in this path.** The evaluator is agisdk's programmatic checks;
the supervisor's stopping conditions are counts of files on disk. A model
labelling its own failures makes the number meaningless (entry 7).

The runner is invoked as a **subprocess**, once per round, so a crash in a round
is a non-zero exit code rather than a dead supervisor — and so the wedged
browsers of that round die with it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from web_agent_eval import cli, records
from web_agent_eval import manifest as manifest_module

RUNNER = ROOT / "scripts" / "run_batch.py"

EXIT_COMPLETE = 0
EXIT_STALLED = 1
EXIT_BUDGET = 2
EXIT_SETUP = 3


def stamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def print_summary(manifest, summary: dict, run_dir: Path) -> None:
    print(f"\n=== run {manifest.run_id} — population {manifest.population}, "
          f"n={manifest.size} ===")
    print(f"  terminal      : {summary['terminal']}/{summary['tasks']}")
    print(f"  pending       : {len(summary['pending'])}")
    print(f"  attempts      : {summary['attempts']} (retries included)")
    print(f"  statuses      : {json.dumps(summary['counts'], sort_keys=True)}")
    print(f"  provider errs : {summary['provider_errors']} (never counted as failures)")
    print(f"  tokens        : {summary['tokens']}")
    if summary["scored"]:
        # Stated over what has been scored so far, and labelled as such. The
        # published rate is feat-006's, against the manifest's own n.
        print(f"  passed        : {summary['passed']}/{summary['scored']} scored "
              f"({summary['rate_over_scored']:.1%} of scored, first terminal attempt each)")
    print(f"  results.tsv   : {records.results_path(run_dir)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    cli.add_run_args(parser)
    parser.add_argument("--stall-rounds", type=int, default=3,
                        help="K: consecutive rounds with no new terminal record "
                             "before the run is called stalled")
    parser.add_argument("--max-rounds", type=int, default=20)
    parser.add_argument("--backoff-s", type=float, default=30.0,
                        help="base backoff after a round that saw provider errors "
                             "or added nothing; doubles, capped at 8x")
    args = parser.parse_args(argv)

    run_dir = cli.run_dir_for(args)
    try:
        manifest = manifest_module.ensure(run_dir, cli.manifest_for(args))
    except (manifest_module.ManifestFrozen, ValueError, RuntimeError) as exc:
        print(f"cannot start: {exc}", file=sys.stderr)
        return EXIT_SETUP

    summary = records.summarise(run_dir, manifest.task_ids)
    if not summary["pending"]:
        # Idempotent: a completed run is read, printed, and left exactly as it
        # was found. Nothing below this line runs, so nothing is written.
        print(f"run {manifest.run_id} is already complete — nothing to do.")
        print_summary(manifest, summary, run_dir)
        return EXIT_COMPLETE

    print(f"supervising {manifest.run_id}: {summary['terminal']}/{summary['tasks']} "
          f"already terminal, {len(summary['pending'])} pending, "
          f"stall after {args.stall_rounds} empty rounds, max {args.max_rounds} rounds")

    log_path = run_dir / "supervise.jsonl"
    # Rounds are numbered across restarts, not from 1 each time a supervisor
    # starts. A resumed run that began again at round 1 would overwrite the
    # round file of the run it is resuming, and a killed run's history is
    # exactly the history worth keeping.
    first_round = 1 + max(
        (int(p.stem.split("_")[1]) for p in (run_dir / "rounds").glob("round_*.json")),
        default=0,
    )
    stalled_rounds = 0
    concurrency = args.concurrency
    exit_code = EXIT_STALLED
    reason = f"round limit of {args.max_rounds} reached without finishing"

    for round_index in range(first_round, first_round + args.max_rounds):
        before = len(records.terminal_task_ids(run_dir))
        command = [
            sys.executable, str(RUNNER),
            *cli.forwarded_args(args),
            "--round", str(round_index),
            "--concurrency", str(concurrency),
        ]
        print(f"\n--- round {round_index} (concurrency {concurrency}) ---", flush=True)
        completed = subprocess.run(command, cwd=ROOT, check=False)
        after_ids = records.terminal_task_ids(run_dir)
        new_terminal = len(after_ids) - before

        round_file = run_dir / "rounds" / f"round_{round_index:03d}.json"
        # A round that was killed never wrote its file. Then the only honest
        # account of it is the records on disk: how many became terminal is
        # known, how many were attempted is not, and saying "0 attempted" would
        # read as an idle round rather than a killed one.
        killed = not round_file.exists()
        round_data = {} if killed else json.loads(round_file.read_text())
        provider_errors = round_data.get("provider_errors", 0)
        # Slow recovery: at most one worker back per round, never above the
        # level this run was configured for (entry 7).
        concurrency = min(args.concurrency, round_data.get("concurrency_end", concurrency) + 1)

        pending = [t for t in manifest.task_ids if t not in after_ids]
        stalled_rounds = 0 if new_terminal else stalled_rounds + 1
        backoff = 0.0
        if pending and (provider_errors or not new_terminal):
            backoff = min(args.backoff_s * (2 ** min(stalled_rounds, 3)), args.backoff_s * 8)

        entry = {
            "ts": stamp(),
            "round": round_index,
            "runner_exit": completed.returncode,
            "attempted": None if killed else len(round_data.get("attempted", [])),
            "round_file_missing": killed,
            "new_terminal": new_terminal,
            "terminal_total": len(after_ids),
            "pending": len(pending),
            "provider_errors": provider_errors,
            "statuses": round_data.get("statuses", {}),
            "retired_processes": len(round_data.get("retired_processes", [])),
            "budget_stop": round_data.get("budget_stop"),
            # Entry 7's site rule had never been exercised before this feature —
            # the pilot ran one task per site. What it costs in scheduling is
            # recorded per round rather than assumed to be free.
            "site_constraint": round_data.get("site_constraint", {}),
            "next_concurrency": concurrency,
            "backoff_s": backoff,
            "stalled_rounds": stalled_rounds,
        }
        with open(log_path, "a") as handle:
            handle.write(json.dumps(entry) + "\n")
        print(f"round {round_index}: attempted "
              f"{'unknown (the runner died before writing its round file)' if killed else entry['attempted']}"
              f", new terminal {new_terminal}, pending {len(pending)}, "
              f"provider errors {provider_errors}, "
              f"retired {entry['retired_processes']}, backoff {backoff:g}s")
        site = entry["site_constraint"]
        if site:
            print(f"  site rule: {site.get('reorders', 0)} launches reordered "
                  f"({site.get('tasks_passed_over', 0)} task-positions passed over), "
                  f"{site.get('blocked_events', 0)} idle-slot events costing "
                  f"{site.get('idle_slot_s', 0):.1f} worker-seconds of "
                  f"{site.get('slot_s_available', 0):.1f} available "
                  f"({(site.get('idle_fraction') or 0):.2%})")

        if completed.returncode == EXIT_BUDGET or round_data.get("budget_stop"):
            exit_code = EXIT_BUDGET
            reason = round_data.get("budget_stop") or "the runner reported the budget exceeded"
            break
        if not pending:
            exit_code = EXIT_COMPLETE
            reason = "every manifest task has a terminal record"
            break
        if stalled_rounds >= args.stall_rounds:
            exit_code = EXIT_STALLED
            reason = (f"{stalled_rounds} consecutive rounds added no terminal record "
                      f"({provider_errors} provider errors in the last one)")
            break
        if completed.returncode not in (0, EXIT_BUDGET):
            print(f"  runner exited {completed.returncode}; counting the round as empty")
        if backoff:
            print(f"  backing off {backoff:g}s before the next round", flush=True)
            time.sleep(backoff)

    summary = records.summarise(run_dir, manifest.task_ids)
    print_summary(manifest, summary, run_dir)
    label = {EXIT_COMPLETE: "COMPLETE", EXIT_STALLED: "STALLED", EXIT_BUDGET: "BUDGET"}
    print(f"\nEXIT {exit_code} ({label[exit_code]}): {reason}")
    if exit_code == EXIT_STALLED:
        print("  no terminal record was invented for the tasks that did not run — "
              "a provider outage is not a wall of task failures (DECISIONS entry 7)")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
