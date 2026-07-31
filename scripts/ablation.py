"""Compare two runs — and refuse to, unless they are comparable.

    uv run python scripts/ablation.py arms --a full102 --b rich102
    uv run python scripts/ablation.py cap  --baseline full102 --higher cap50

`feat-007` asks two questions of the same records, and both are subtractions
between two runs. A subtraction between two runs is only meaningful if the runs
differ in exactly one thing, so the first thing this script does in either mode
is **check that and stop if it is not true**. The comparison is not asserted in
prose after the fact; it is a precondition the tool enforces before it will print
a delta.

    arms   the ablation. Same task ids, same caps, same model, same entrypoint,
           **different observation richness**. Both raw rates with their n, and
           the delta — reported whatever its size, including zero.

    cap    the cap-sensitivity measurement. Same richness, same model, a
           **higher step cap**, and a task list that is exactly the set the
           baseline ran out of steps on. How many convert to passes.

Neither mode edits anything. Both read `manifest.json` and `records/*.json`
through `scoring.score`, which is `feat-005`'s reproduces-from-disk path, so a
number printed here is the number stored on disk and nothing else.

Exit codes:
    0  the two runs are comparable and the comparison was printed
    1  they are not comparable, and what differs is named
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from web_agent_eval import scoring


class NotComparable(RuntimeError):
    """The two runs differ in more, or less, than the one thing being varied."""


def load(runs_dir: str, run_id: str) -> tuple[dict, dict]:
    run_dir = Path(runs_dir) / run_id
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise NotComparable(f"no manifest at {manifest_path}")
    return json.loads(manifest_path.read_text()), scoring.score(run_dir)


def level_of(manifest: dict) -> str:
    """The richness a run executed at.

    Manifests written before `feat-007` added the field carry it in `note` and
    nowhere else. Rather than guess, this reads the note for the exact phrase
    the CLI writes — and a run whose level cannot be established is refused,
    because an ablation between two arms one of which is "probably lean" is not
    an ablation.
    """
    level = manifest.get("level") or ""
    if level:
        return level
    note = manifest.get("note") or ""
    for token in ("level lean", "level rich"):
        if token in note:
            return token.split()[1]
    raise NotComparable(
        f"run {manifest['run_id']!r} does not record which observation richness it "
        f"ran at: no `level` field and no 'level <name>' in its note. Two runs "
        f"cannot be subtracted when one of them will not say what it was."
    )


def require_same(a_manifest: dict, b_manifest: dict, fields: tuple[str, ...]) -> list[str]:
    """The fields that must match, and the human-readable proof that they do."""
    proof = []
    for field in fields:
        left, right = a_manifest.get(field), b_manifest.get(field)
        if left != right:
            raise NotComparable(
                f"{field} differs between the two runs, so they are not a comparison "
                f"of one thing:\n    {a_manifest['run_id']}: {left!r}\n"
                f"    {b_manifest['run_id']}: {right!r}"
            )
        shown = f"{len(left)} ids, identical" if field == "task_ids" else repr(left)
        proof.append(f"  same {field:<18} {shown}")
    return proof


# --------------------------------------------------------------------------
# reading one run
# --------------------------------------------------------------------------


def cap_breakdown(payload: dict) -> dict[str, int]:
    """Which cap ended each capped episode.

    Entry 11 fixes the order — wall clock, then tokens, then steps — so an arm
    whose episodes are ending on a different cap from the other arm's is not
    being limited by the same thing, and a delta between them would be partly a
    delta between two constraints. Published rather than assumed identical.
    """
    out: dict[str, int] = {}
    for row in payload["tasks"]:
        if row["status"] == "capped":
            out[row["cap"] or "unknown"] = out.get(row["cap"] or "unknown", 0) + 1
    return out


def arm_summary(manifest: dict, payload: dict) -> dict:
    terminal = [r for r in payload["tasks"] if r["terminal"]]
    return {
        "run_id": payload["run_id"],
        "level": level_of(manifest),
        "n": payload["manifest_n"],
        "terminal": payload["terminal"],
        "passed": payload["passed"],
        "rate_over_manifest": payload["rate_over_manifest"],
        "rate_over_terminal": payload["rate_over_terminal"],
        "counts": payload["counts"],
        "caps": manifest["caps"],
        "cap_breakdown": cap_breakdown(payload),
        "agent_tokens": payload["agent"]["tokens"],
        "steps": payload["steps"],
        "wall_clock_s": payload["wall_clock_s"],
        "judge_usd": payload["judge"]["usd"],
        "passed_ids": sorted(r["task_id"] for r in terminal if r["passed"]),
        "by_task": {r["task_id"]: r for r in payload["tasks"]},
    }


def render_arm(arm: dict) -> str:
    rate = ("n/a" if arm["rate_over_manifest"] is None
            else f"{arm['rate_over_manifest']:.2%}")
    caps = arm["cap_breakdown"]
    by_cap = json.dumps(caps, sort_keys=True) if caps else "nothing capped"
    return "\n".join([
        (f"  {arm['run_id']:<10} level {arm['level']:<5} n = {arm['n']:<4} "
         f"passed {arm['passed']:<4} rate {rate}"),
        f"             {json.dumps(arm['counts'], sort_keys=True)}",
        f"             capped by: {by_cap}",
        (f"             agent tokens {arm['agent_tokens']['total']:,} "
         f"(mean {arm['agent_tokens']['mean']:,.0f}), "
         f"steps mean {arm['steps']['mean']}, "
         f"wall clock mean {arm['wall_clock_s']['mean']}s"),
    ])


# --------------------------------------------------------------------------
# the exact test on the discordant pairs
# --------------------------------------------------------------------------


def mcnemar_exact(only_a: int, only_b: int) -> float:
    """Two-sided exact p for a paired pass/fail flip count (McNemar's test).

    The same 102 tasks are run twice, so the arms are **paired** and the
    informative quantity is the tasks that changed verdict, not the two totals.
    Under the null — richness changes nothing, and each flip is a coin toss —
    the number flipping one way is Binomial(discordant, 0.5). Exact rather than
    chi-square because the counts here are small enough that the approximation
    is not trustworthy, and `math.comb` makes exact free.

    This is a statement about *this* run pair only. It says nothing about
    whether a rerun would land in the same place for reasons other than chance.
    """
    n = only_a + only_b
    if n == 0:
        return 1.0
    k = min(only_a, only_b)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


# --------------------------------------------------------------------------
# mode: arms
# --------------------------------------------------------------------------


def arms(args) -> int:
    a_manifest, a_score = load(args.runs_dir, args.a)
    b_manifest, b_score = load(args.runs_dir, args.b)

    print("=== is this a comparison of one thing? ===")
    proof = require_same(a_manifest, b_manifest,
                         ("task_ids", "caps", "model", "episode_entrypoint", "population"))
    a_level, b_level = level_of(a_manifest), level_of(b_manifest)
    if a_level == b_level:
        raise NotComparable(
            f"both runs are at richness {a_level!r}. An ablation whose arms are the "
            f"same level measures nothing."
        )
    print("\n".join(proof))
    print(f"  differs: level         {a_level!r} vs {b_level!r}  <- the ablation")

    a, b = arm_summary(a_manifest, a_score), arm_summary(b_manifest, b_score)
    for arm in (a, b):
        if arm["terminal"] != arm["n"]:
            print(f"\n  NOTE: {arm['run_id']} has {arm['terminal']} terminal of "
                  f"{arm['n']} — the rate below is over what has been scored, not "
                  f"over the manifest.")

    print("\n=== both arms, raw ===")
    print(render_arm(a))
    print(render_arm(b))

    print("\n=== the delta ===")
    if a["rate_over_manifest"] is None or b["rate_over_manifest"] is None:
        print("  not stated: one arm is incomplete, and a delta between a finished "
              "run and an unfinished one is not a delta.")
        return 1
    delta = b["rate_over_manifest"] - a["rate_over_manifest"]
    print(f"  {b['level']} - {a['level']} = {b['passed']}/{b['n']} - {a['passed']}/{a['n']} "
          f"= {b['rate_over_manifest']:.2%} - {a['rate_over_manifest']:.2%} "
          f"= {delta:+.2%} ({b['passed'] - a['passed']:+d} tasks)")

    shared = [t for t in a_manifest["task_ids"]]
    both = [t for t in shared if a["by_task"][t]["passed"] and b["by_task"][t]["passed"]]
    only_a = [t for t in shared if a["by_task"][t]["passed"] and not b["by_task"][t]["passed"]]
    only_b = [t for t in shared if b["by_task"][t]["passed"] and not a["by_task"][t]["passed"]]
    neither = len(shared) - len(both) - len(only_a) - len(only_b)
    print("\n  the same tasks, paired:")
    print(f"    passed in both      {len(both):>4}")
    print(f"    only {a['level']:<14} {len(only_a):>4}  {', '.join(only_a) or '-'}")
    print(f"    only {b['level']:<14} {len(only_b):>4}  {', '.join(only_b) or '-'}")
    print(f"    passed in neither   {neither:>4}")
    p = mcnemar_exact(len(only_a), len(only_b))
    print(f"    McNemar exact, two-sided, on the {len(only_a) + len(only_b)} discordant "
          f"pairs: p = {p:.3f}")
    print(f"    {'this delta is not distinguishable from chance at n=' + str(a['n'])
            if p > 0.05 else 'the flip counts are lopsided beyond chance at p<0.05'}")

    print("\n=== what each arm cost ===")
    ratio = (b["agent_tokens"]["total"] / a["agent_tokens"]["total"]
             if a["agent_tokens"]["total"] else float("nan"))
    print(f"  agent tokens  {a['run_id']} {a['agent_tokens']['total']:,}  ->  "
          f"{b['run_id']} {b['agent_tokens']['total']:,}   x{ratio:.2f}")
    print(f"  judge USD     {a['run_id']} ${a['judge_usd']:.6f}  ->  "
          f"{b['run_id']} ${b['judge_usd']:.6f}")
    print("  no dollar figure for the agent column: z.ai publishes no rate for this "
          "Coding Plan key (DECISIONS entry 6).")
    return 0


# --------------------------------------------------------------------------
# mode: cap sensitivity
# --------------------------------------------------------------------------


def cap(args) -> int:
    base_manifest, base_score = load(args.runs_dir, args.baseline)
    high_manifest, high_score = load(args.runs_dir, args.higher)

    base = arm_summary(base_manifest, base_score)
    high = arm_summary(high_manifest, high_score)

    print("=== is this the same setting with a bigger step budget? ===")
    proof = require_same(base_manifest, high_manifest, ("model", "episode_entrypoint"))
    if base["level"] != high["level"]:
        raise NotComparable(
            f"richness differs ({base['level']!r} vs {high['level']!r}). Then a task "
            f"that converts might have converted because it could see more, not "
            f"because it had more steps."
        )
    capped_ids = sorted(t for t, r in base["by_task"].items() if r["status"] == "capped")
    if sorted(high_manifest["task_ids"]) != capped_ids:
        raise NotComparable(
            f"the higher-cap run's task list is not exactly the tasks "
            f"{base['run_id']} ran out of steps on:\n"
            f"    capped in {base['run_id']}: {len(capped_ids)}\n"
            f"    in {high['run_id']}'s manifest: {len(high_manifest['task_ids'])}\n"
            f"    only in one: "
            f"{sorted(set(capped_ids) ^ set(high_manifest['task_ids']))}"
        )
    base_steps = base["caps"]["max_steps"]
    high_steps = high["caps"]["max_steps"]
    if high_steps <= base_steps:
        raise NotComparable(
            f"the 'higher' run's step cap is {high_steps}, not above the baseline's "
            f"{base_steps}. There is no cap sensitivity to measure."
        )
    print("\n".join(proof))
    print(f"  same level             {base['level']!r}")
    print(f"  the higher run's tasks are exactly the {len(capped_ids)} the baseline capped")
    print(f"  differs: max_steps     {base_steps} -> {high_steps}  <- the subject")
    for other in ("max_tokens", "max_wall_clock_s"):
        b_value, h_value = base["caps"][other], high["caps"][other]
        per_step_b, per_step_h = b_value / base_steps, h_value / high_steps
        same = abs(per_step_b - per_step_h) < max(1.0, per_step_b * 1e-9)
        verdict = "(allowance per step unchanged)" if same else "(ALLOWANCE PER STEP CHANGED)"
        print(f"  also:    {other:<16} {b_value:g} -> {h_value:g}"
              f"   per step {per_step_b:g} -> {per_step_h:g}   {verdict}")

    print(f"\n=== the {len(capped_ids)} tasks that ran out of steps at {base_steps}, "
          f"re-run at {high_steps} ===")
    counts = high["counts"]
    converted = sorted(t for t in capped_ids if high["by_task"][t]["passed"])
    still_capped = sorted(t for t in capped_ids if high["by_task"][t]["status"] == "capped")
    now_failed = sorted(t for t in capped_ids if high["by_task"][t]["status"] == "failed")
    errored = sorted(t for t in capped_ids if high["by_task"][t]["status"] == "errored")
    pending = sorted(t for t in capped_ids if not high["by_task"][t]["terminal"])
    print(f"  {json.dumps(counts, sort_keys=True)}")
    print(f"  converted to a pass  {len(converted):>4}  {', '.join(converted) or '-'}")
    print(f"  still out of steps   {len(still_capped):>4}")
    print(f"  now terminal, failed {len(now_failed):>4}  (used the extra steps, "
          f"answered, and was wrong)")
    print(f"  errored              {len(errored):>4}")
    if pending:
        print(f"  NOT TERMINAL         {len(pending):>4}  {', '.join(pending)} — "
              f"the numbers below are over what ran")

    if converted:
        steps_used = [(t, high["by_task"][t]["steps"]) for t in converted]
        shown = ", ".join(f"{t.split('.')[-1]}={s}" for t, s in steps_used)
        print(f"\n  steps the converted tasks needed: {shown}")
        beyond = [s for _t, s in steps_used if s is not None and s > base_steps]
        print(f"  {len(beyond)} of {len(converted)} needed more than {base_steps} steps — "
              f"the rest passed inside the old budget on this attempt, which the "
              f"baseline's own attempt did not")

    terminal_high = high["terminal"]
    if terminal_high:
        print(f"\n  conversion rate: {len(converted)}/{terminal_high} = "
              f"{len(converted) / terminal_high:.1%} of the re-run tasks")

    print("\n=== what that does to the published rate, stated as a construction ===")
    carried = base["passed"]
    print(f"  {base['run_id']} at {base_steps} steps:  {carried}/{base['n']} = "
          f"{base['rate_over_manifest']:.2%}   <- measured, and it stands")
    composite = carried + len(converted)
    print(f"  the same population at {high_steps} steps: "
          f"({carried} + {len(converted)})/{base['n']} = {composite}/{base['n']} = "
          f"{composite / base['n']:.2%}")
    print(f"    construction: the {base['n'] - len(capped_ids)} tasks that did NOT run "
          f"out of steps keep their {base_steps}-step outcome, because a step cap can "
          f"only bind on an episode that reached it; the {len(capped_ids)} that did "
          f"were re-run at {high_steps} and contribute their new outcome.")
    print(f"    it is a composite of two runs, not a run. It carries its own cap and "
          f"its own construction wherever it is quoted, and it does not replace "
          f"{base['rate_over_manifest']:.2%} at {base_steps} steps.")

    print("\n=== cost of the extra steps ===")
    base_capped_tokens = sum(base["by_task"][t]["agent_tokens"] or 0 for t in capped_ids)
    high_tokens = high["agent_tokens"]["total"]
    ratio = f"   x{high_tokens / base_capped_tokens:.2f}" if base_capped_tokens else ""
    print(f"  the same {len(capped_ids)} tasks: {base_capped_tokens:,} agent tokens at "
          f"{base_steps} steps  ->  {high_tokens:,} at {high_steps}{ratio}")
    base_capped_secs = sum(base["by_task"][t]["wall_clock_s"] or 0 for t in capped_ids)
    print(f"  episode seconds: {base_capped_secs:,.0f}  ->  "
          f"{high['wall_clock_s']['total']:,.0f}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs-dir", default="runs")
    sub = parser.add_subparsers(dest="mode", required=True)

    arms_parser = sub.add_parser("arms", help="the richness ablation")
    arms_parser.add_argument("--a", required=True, help="run id of the first arm")
    arms_parser.add_argument("--b", required=True, help="run id of the second arm")
    arms_parser.set_defaults(func=arms)

    cap_parser = sub.add_parser("cap", help="the cap-sensitivity measurement")
    cap_parser.add_argument("--baseline", required=True)
    cap_parser.add_argument("--higher", required=True)
    cap_parser.set_defaults(func=cap)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except NotComparable as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
