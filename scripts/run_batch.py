"""One round of a batch run: every manifest task that is not terminal yet.

    uv run python scripts/run_batch.py --run-id smoke --population explicit \
        --tasks v1.gomail-2,v1.staynb-1 --concurrency 2

Writes the manifest if this run is new (never edits one that exists), attempts
the pending tasks in worker processes, and returns. It does not loop and it
does not decide the run is over — `scripts/supervise.py` does that, per
docs/DECISIONS.md entry 7.

Exit codes:
    0  the round ran
    2  the run-level token or wall-clock budget was exceeded
    1  the run could not be set up (a frozen manifest was contradicted, say)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from web_agent_eval import batch, cli, records
from web_agent_eval import manifest as manifest_module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    cli.add_run_args(parser)
    parser.add_argument("--round", type=int, default=1)
    args = parser.parse_args(argv)

    run_dir = cli.run_dir_for(args)
    try:
        manifest = manifest_module.ensure(run_dir, cli.manifest_for(args))
    except (manifest_module.ManifestFrozen, ValueError, RuntimeError) as exc:
        print(f"cannot start: {exc}", file=sys.stderr)
        return 1

    # Workers live in this process group, so one signal reaches the browsers too.
    batch.install_kill_on_parent_death()

    print(f"run {manifest.run_id}: population {manifest.population} "
          f"(n={manifest.size}), caps {manifest.caps}, entrypoint "
          f"{manifest.episode_entrypoint}")

    result = batch.run_round(
        run_dir,
        manifest,
        round_index=args.round,
        concurrency=args.concurrency,
        budget=cli.budget_for(args),
        run_started=cli.run_started_monotonic(manifest),
        level=args.level,
    )
    batch.write_round_log(run_dir, result)

    summary = records.summarise(run_dir, manifest.task_ids)
    print(f"round {result.round} done in {result.elapsed_s:.1f}s: "
          f"attempted {len(result.attempted)}, new terminal {len(result.new_terminal)}, "
          f"provider errors {result.provider_errors}, "
          f"concurrency {result.concurrency_start} -> {result.concurrency_end}")
    print(f"run state: {summary['terminal']}/{summary['tasks']} terminal, "
          f"{len(summary['pending'])} pending, {summary['attempts']} attempts, "
          f"{summary['tokens']} tokens")
    print(json.dumps(summary["counts"], sort_keys=True))

    if result.budget_stop:
        print(f"EXIT 2: {result.budget_stop}")
        return batch.BUDGET_EXIT_CODE
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
