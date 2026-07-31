"""Everything that must be true before `feat-006`'s first browser starts.

    uv run python scripts/preflight.py --run-id full102 --population 102 \
        --concurrency 3 --budget-tokens 8000000 --budget-wall-clock-s 10800

Writes `runs/<run-id>/manifest.json` — **and nothing else ever writes it**, so
the population, the exclusions and the probes below are fixed before a single
task runs. `scripts/run_batch.py` refuses a real run whose manifest carries no
reachability record, which is what makes this step non-optional rather than
merely recommended.

Four things are checked, and each one is a way the headline number comes out
wrong without anything looking broken:

1. **The judge is live and pointed at OpenAI.** 55 of the 102 tasks carry an
   `llm_boolean` eval. A judge that is down, or one silently redirected to z.ai
   by a leaked `OPENAI_BASE_URL`, makes more than half the result wrong in a way
   nothing downstream can detect (DECISIONS entries 10 and 13). The assertion is
   run **with its control**, because a gate never seen to fail is not evidence.
2. **Every replica host still answers.** Omnizon died between planning and now
   (entry 5). A second host disappearing mid-run must be a recorded exclusion,
   not ten mystery failures — so reachability is measured here and frozen into
   the manifest. If it disagrees with the exclusions the population is built
   from, this **stops**: the denominator is a decision taken before the run, not
   one the runner may take for itself.
3. **The endpoint serves the model that was asked for.** Requested and served
   are different facts (entry 9).
4. **The manifest says what it should.** It is printed and re-read from disk,
   with the population size, the exclusion count and reason, the concurrency and
   the date checked against what was asked for.

Exit codes:
    0  every check passed; the manifest is on disk and the run may start
    1  a check failed — reported, not worked around
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from web_agent_eval import cli, glm, judge, sites
from web_agent_eval import manifest as manifest_module

EXPECTED_UNREACHABLE = set(manifest_module.UNREACHABLE_SITES)


def check_judge(task_ids: list[str]) -> tuple[bool, dict]:
    """Assert the judge, then break the assertion on purpose and watch it refuse.

    The control is `feat-005`'s: point `OPENAI_BASE_URL` at z.ai and confirm
    `require()` refuses. Without it, "the judge is fine" is a sentence that
    would also be printed by a check that cannot fail.
    """
    import os

    needed = judge.judged_in(task_ids)
    print(f"\n=== judge ===\n  {len(needed)} of {len(task_ids)} tasks carry an llm_boolean eval")
    try:
        info = judge.require()
    except (judge.JudgeUnavailable, judge.JudgeMisrouted) as exc:
        print(f"  FAILED: {exc}")
        return False, {"tasks_needing_judge": len(needed), "error": str(exc)}

    print(f"  model {info['model_default']}  base_url {info['base_url']} "
          f"(host {info['host']})  OPENAI_BASE_URL={info['OPENAI_BASE_URL_env']!r}")

    previous = os.environ.get("OPENAI_BASE_URL")
    os.environ["OPENAI_BASE_URL"] = glm.CODING_PLAN_BASE_URL
    try:
        judge.require()
        print("  CONTROL FAILED: the assertion passed with OPENAI_BASE_URL "
              "pointed at z.ai, so it is vacuous and proves nothing")
        return False, {"tasks_needing_judge": len(needed),
                       "error": "the judge assertion is vacuous"}
    except judge.JudgeMisrouted as exc:
        print(f"  control: refused, as it must — {str(exc).splitlines()[0]}")
    finally:
        if previous is None:
            os.environ.pop("OPENAI_BASE_URL", None)
        else:
            os.environ["OPENAI_BASE_URL"] = previous

    # And one live call, because "configured correctly" is not "answering".
    from openai import OpenAI

    try:
        client = OpenAI()
        response = client.chat.completions.create(
            model=info["model_default"],
            messages=[{"role": "user", "content": "Reply with the single character 1."}],
            max_tokens=2,
            temperature=0.0,
        )
    except Exception as exc:  # noqa: BLE001 — any failure here stops the run
        print(f"  FAILED: the judge model did not answer: {type(exc).__name__}: {exc}")
        return False, {"tasks_needing_judge": len(needed),
                       "error": f"{type(exc).__name__}: {exc}"}
    served = getattr(response, "model", None)
    usage = getattr(response, "usage", None)
    print(f"  live call: requested {info['model_default']!r} -> served {served!r}, "
          f"reply {response.choices[0].message.content!r}, "
          f"usage {getattr(usage, 'total_tokens', None)} tokens")
    return True, {
        "tasks_needing_judge": len(needed),
        "endpoint": info,
        "served": served,
        "control": "passed — require() refused when OPENAI_BASE_URL pointed at z.ai",
    }


def check_sites(attempts: int) -> tuple[bool, list[dict]]:
    print(f"\n=== site reachability ({attempts} probes each, redirects followed) ===")
    entries = sites.probe_all(attempts=attempts)
    print(sites.render(entries))
    down = sites.unreachable_sites(entries)
    print(f"  unreachable: {sorted(down) or 'none'}")
    if down != EXPECTED_UNREACHABLE:
        print("\n  STOP: the reachable set has changed since DECISIONS entry 5.")
        print(f"    the population excludes {sorted(EXPECTED_UNREACHABLE)}")
        print(f"    this probe says {sorted(down)} are down")
        print("    Which tasks a run attempts is decided before the run, not by the "
              "runner after seeing what fails (entry 7). Record the new exclusion "
              "and its reason first; do not start a run whose denominator would be "
              "silently wrong.")
        return False, entries
    return True, entries


def check_model(model: str) -> tuple[bool, dict]:
    print("\n=== served model ===")
    try:
        info = glm.served_model(model)
    except Exception as exc:  # noqa: BLE001
        print(f"  FAILED: {type(exc).__name__}: {exc}")
        return False, {"requested": model, "error": f"{type(exc).__name__}: {exc}"}
    print(f"  requested {info['requested']!r} -> served {info['served']!r} "
          f"at {info['base_url']} ({info['latency_s']}s)")
    if not info["served"]:
        print("  FAILED: the endpoint reported no model string for this completion")
        return False, info
    return True, info


def check_manifest(run_dir: Path, args, entries: list[dict]) -> bool:
    """Re-read the manifest from disk and check it says what was asked for."""
    manifest = manifest_module.load(run_dir)
    print(f"\n=== manifest {run_dir / 'manifest.json'} (frozen from here on) ===")
    print(f"  run_id       {manifest.run_id}")
    print(f"  created      {manifest.created}")
    print(f"  population   {manifest.population}  n={manifest.size}")
    print(f"  sites        {len(manifest.sites)}: {', '.join(manifest.sites)}")
    print(f"  concurrency  {manifest.concurrency}")
    print(f"  model        requested {manifest.model!r}, "
          f"served {manifest.served_model.get('served')!r}")
    print(f"  caps         {manifest.caps}")
    print(f"  entrypoint   {manifest.episode_entrypoint}")

    reasons: dict[str, int] = {}
    for exclusion in manifest.exclusions:
        reasons[exclusion["reason"]] = reasons.get(exclusion["reason"], 0) + 1
    print(f"  exclusions   {len(manifest.exclusions)}")
    for reason, count in sorted(reasons.items()):
        print(f"    {count:>3d}  {reason}")

    failures = []
    if manifest.population != args.population:
        failures.append(f"population is {manifest.population}, asked for {args.population}")
    if manifest.size != int(args.population):
        failures.append(f"n is {manifest.size}, population {args.population} means "
                        f"{int(args.population)}")
    if manifest.concurrency != args.concurrency:
        failures.append(f"concurrency is {manifest.concurrency}, asked for {args.concurrency}")
    if len(manifest.exclusions) != 112 - manifest.size:
        failures.append(f"{len(manifest.exclusions)} exclusions for {manifest.size} of 112 tasks")
    excluded_sites = {manifest_module.site_of(e["task_id"]) for e in manifest.exclusions}
    if excluded_sites != EXPECTED_UNREACHABLE:
        failures.append(f"exclusions cover sites {sorted(excluded_sites)}, "
                        f"expected {sorted(EXPECTED_UNREACHABLE)}")
    if not all("451" in e["reason"] for e in manifest.exclusions):
        failures.append("an exclusion does not give HTTP 451 as its reason")
    today = datetime.now(UTC).date().isoformat()
    if not manifest.created.startswith(today):
        failures.append(f"created {manifest.created} is not today ({today})")
    if not manifest.served_model.get("served"):
        failures.append("no served model string recorded")
    if len(manifest.site_reachability) != len(entries):
        failures.append("the reachability probe is not recorded in the manifest")
    if sites.unreachable_sites(manifest.site_reachability) != EXPECTED_UNREACHABLE:
        failures.append("the manifest's reachability record disagrees with its exclusions")

    if failures:
        print("\n  MANIFEST CHECK FAILED:")
        for failure in failures:
            print(f"    - {failure}")
        return False
    print("\n  checked: population, n, exclusion count and reason, sites, concurrency, "
          "served model, reachability record, date")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    cli.add_run_args(parser)
    parser.add_argument("--probe-attempts", type=int, default=sites.DEFAULT_ATTEMPTS)
    args = parser.parse_args(argv)

    run_dir = cli.run_dir_for(args)
    print(f"=== preflight for {args.run_id}: population {args.population}, "
          f"concurrency {args.concurrency} ===")
    if (run_dir / "manifest.json").exists():
        print(f"\ncannot start: {run_dir / 'manifest.json'} already exists. A manifest is "
              f"written once and never edited (DECISIONS entry 7); use a new --run-id, or "
              f"resume the existing run with scripts/supervise.py.", file=sys.stderr)
        return 1

    wanted_ids, _ = manifest_module.population(args.population)
    ok_judge, judge_info = check_judge(wanted_ids)
    ok_sites, entries = check_sites(args.probe_attempts)
    ok_model, model_info = check_model(args.model)

    if not (ok_judge and ok_sites and ok_model):
        print("\nPREFLIGHT FAILED — no manifest was written and no task ran.", file=sys.stderr)
        return 1

    manifest = manifest_module.ensure(run_dir, manifest_module.build(
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
        note=args.note or f"concurrency {args.concurrency}, level {args.level}; "
                          f"per-task wall clock at N>1 is not comparable to sequential "
                          f"(DECISIONS entry 7)",
        site_reachability=entries,
        served_model=model_info,
    ))
    (run_dir / "preflight.json").write_text(json.dumps({
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "judge": judge_info,
        "sites": entries,
        "served_model": model_info,
    }, indent=2) + "\n")

    if not check_manifest(run_dir, args, entries):
        print("\nPREFLIGHT FAILED after writing the manifest — do not start this run "
              "under this id.", file=sys.stderr)
        return 1

    print(f"\nPREFLIGHT PASSED — {manifest.size} tasks, judge live, "
          f"{len(entries) - len(EXPECTED_UNREACHABLE)} of {len(entries)} hosts up.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
