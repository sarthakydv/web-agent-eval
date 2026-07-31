"""Project `feat-006`'s cost and runtime from a pilot that actually ran.

    uv run python scripts/project_run.py --from-run pilot --population 102

`feat-006` is a long unattended run and it deserves to be scheduled against a
number rather than a hope. Every input here is measured — the per-task token
mean and the per-task wall clock come from `runs/<pilot>/score.json`, the round
wall clock from that round's own log, and the judged-task count from the
installed REAL task configs. Nothing is estimated; the multiplication is printed
so the arithmetic can be checked rather than trusted.

Read the caveats it prints. A projection from 10 tasks is a projection from 10
tasks, and the dominant term — how often an episode caps on steps — is the one
the pilot measures least well.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from web_agent_eval import judge
from web_agent_eval import manifest as manifest_module


def llm_eval_count(task_ids: list[str]) -> tuple[int, int]:
    """(tasks with an llm_boolean eval, total llm_boolean evals) over `task_ids`.

    Not the same number: a task can carry more than one such criterion, and each
    one is a separate judge call. Projecting judge cost per *task* would
    undercount wherever that is true.
    """
    table = {t: evals for t, _site, evals in manifest_module._task_table()}
    tasks = 0
    evals = 0
    for task_id in task_ids:
        n = sum(1 for e in table.get(task_id, []) if e == manifest_module.JUDGE_EVAL_TYPE)
        if n:
            tasks += 1
            evals += n
    return tasks, evals


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-run", required=True, help="a pilot run id with a score.json")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--population", default="102", choices=manifest_module.POPULATIONS)
    parser.add_argument("--round", type=int, default=1)
    args = parser.parse_args(argv)

    run_dir = Path(args.runs_dir) / args.from_run
    score = json.loads((run_dir / "score.json").read_text())
    round_log = json.loads((run_dir / "rounds" / f"round_{args.round:03d}.json").read_text())
    target, _ = manifest_module.population(args.population)
    n = len(target)

    pilot_n = score["terminal"]
    agent = score["agent"]["tokens"]
    wall = score["wall_clock_s"]
    concurrency = round_log["concurrency_end"]
    round_s = round_log["elapsed_s"]
    j = score["judge"]

    print(f"=== projecting {args.population} (n={n}) from run '{args.from_run}' "
          f"({pilot_n} tasks, concurrency {concurrency}) ===\n")

    print("MEASURED, from the pilot's stored records:")
    print(f"  agent tokens per task   mean {agent['mean']:,.1f}  "
          f"min {agent['min']:,}  max {agent['max']:,}  (n={agent['n']})")
    print(f"  wall clock per task     mean {wall['mean']:.1f}s  "
          f"min {wall['min']:.1f}s  max {wall['max']:.1f}s  (n={wall['n']})")
    print(f"  round wall clock        {round_s:.1f}s for {pilot_n} tasks at concurrency "
          f"{concurrency}")
    print(f"  judge                   {j['calls']} calls over {j['tasks_judged']} of "
          f"{j['tasks_needing_judge']} tasks needing one; "
          f"{j['tokens']['prompt']} prompt + {j['tokens']['completion']} completion tokens")
    print()

    # --- agent tokens ---
    tok_mean = n * agent["mean"]
    tok_lo = n * agent["min"]
    tok_hi = n * agent["max"]
    print("AGENT TOKENS (no dollar figure — z.ai publishes no rate for this Coding Plan key)")
    print(f"  central   {n} x {agent['mean']:,.1f} = {tok_mean:,.0f} tokens")
    print(f"  bounds    {n} x {agent['min']:,} = {tok_lo:,.0f}  ..  "
          f"{n} x {agent['max']:,} = {tok_hi:,.0f}")
    print("  the bounds are every task behaving like the cheapest / dearest one measured,")
    print("  not a confidence interval — 10 tasks does not support one.")
    print()

    # --- wall clock, two ways ---
    per_task_round = round_s / pilot_n
    from_round = n * per_task_round
    from_sum = n * (wall["mean"] / concurrency)
    print(f"WALL CLOCK at concurrency {concurrency}")
    print(f"  from the round   {round_s:.1f}s / {pilot_n} = {per_task_round:.2f}s per task"
          f"  ->  {n} x {per_task_round:.2f} = {from_round:,.0f}s = "
          f"{from_round / 60:.1f} min")
    print(f"  from the sum     {wall['mean']:.1f}s / {concurrency} = {wall['mean'] / concurrency:.2f}s"
          f" per task  ->  {n} x {wall['mean'] / concurrency:.2f} = {from_sum:,.0f}s = "
          f"{from_sum / 60:.1f} min")
    spread = abs(from_round - from_sum) / max(from_round, from_sum)
    print(f"  the two agree within {spread * 100:.1f}%. The first is the one to schedule against:")
    print("  it is the clock the run actually ran on, scheduling gaps included.")
    print()

    # --- judge ---
    judged_tasks, judged_evals = llm_eval_count(target)
    per_call_prompt = j["tokens"]["prompt"] / j["calls"] if j["calls"] else 0
    per_call_completion = j["tokens"]["completion"] / j["calls"] if j["calls"] else 0
    prompt_total = judged_evals * per_call_prompt
    completion_total = judged_evals * per_call_completion
    cost = judge.usd(round(prompt_total), round(completion_total))
    print("JUDGE COST (OpenAI publishes a rate, so this one is in dollars)")
    print(f"  {judged_tasks} of the {n} tasks carry an llm_boolean eval, "
          f"{judged_evals} such evals in total")
    print(f"  measured per call: {per_call_prompt:.1f} prompt + {per_call_completion:.1f} "
          f"completion tokens")
    print(f"  {judged_evals} x {per_call_prompt:.1f} = {prompt_total:,.0f} prompt tokens; "
          f"{judged_evals} x {per_call_completion:.1f} = {completion_total:,.0f} completion")
    print(f"  ${judge.GPT_41_USD_PER_1M['input']}/1M x {prompt_total:,.0f} + "
          f"${judge.GPT_41_USD_PER_1M['output']}/1M x {completion_total:,.0f} = ${cost:.4f}")
    print(f"  rate source: {judge.PRICE_SOURCE}")
    print("  this is the CEILING: it assumes every judged task's agent answers, so every")
    print("  eval reaches the judge. An agent that caps without answering costs $0 there —")
    print(f"  {j['tasks_needing_judge'] - j['tasks_judged']} of {j['tasks_needing_judge']} "
          f"did exactly that in the pilot.")
    print()

    print("CAVEATS, and they are not decoration:")
    print(f"  * {pilot_n} tasks, one per reachable site, chosen for eval-type coverage. Not a")
    print("    random sample, so this is a cost projection and NOT a success-rate estimate.")
    print("  * the dominant term is how often an episode caps on steps. Capped episodes cost")
    print("    an order of magnitude more than passing ones, and the cap rate is the thing")
    print(f"    {pilot_n} tasks measures worst.")
    print("  * the pilot ran one task per site, so entry 7's 'no two episodes on one site'")
    print(f"    rule never bound. Over {n} tasks on 10 sites it binds only in the last few,")
    print("    but it can only make the run slower than this, never faster.")
    print("  * a resumed run repeats no terminal task, so a restart adds setup, not episodes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
