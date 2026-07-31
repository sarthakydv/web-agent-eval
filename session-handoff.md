# Session Handoff — web-agent-eval (P3)

## Current Objective

- **Goal:** Measure a web agent on REAL (112 tasks, 11 deterministic replica
  sites) with every number traceable to something that actually ran.
- **Current status: the project is complete.** `feat-001` `[GATE]` **passed**,
  `feat-002` … `feat-008` **done**, `feat-008` being the last feature in the
  list. **The headline measurement exists: 18 of 102 = 17.6%**, against
  REAL's published **≤41%** baseline, run 2026-07-31 on `glm-4.6` at concurrency
  3 and scored by REAL's own `gpt-4.1` judge. Entry 16.
- **`feat-007` answered both questions entry 16 left open** (entry 17).
  `rich` observation: **23/102 = 22.55%** against `lean`'s 17.65%, **+4.9 points
  at p = 0.302** (McNemar exact, 15 discordant pairs) for **5.18x the tokens** —
  no effect detected at this n. Cap sensitivity: the 56 capped tasks re-run at
  **50 steps** converted **3**, and **40 still ran out of steps**, so
  **17.6% is a capability number, not a cap artefact.** Both figures carry their
  own `n` and cap and neither replaces the headline.
- **The noise floor is now measured: 17.9%.** Ten of those 56 tasks terminated
  inside the old 25-step budget on the re-run, at `temperature=0`. Any future
  claim about a delta of a few tasks is working underneath that.
- **Deterministic replicas are easier than live sites, so 17.6% is not
  comparable to a live-web score.** That qualifier goes with the number wherever
  it appears — README, DECISIONS, the evidence field.
- **The reachable population is 102, not 47 and not 112.** 55 tasks judged by
  `gpt-4.1`, 47 by `jmespath` checks; the 10 omnizon tasks are out at HTTP 451,
  and that count and reason travel with the rate.
- **`feat-008` wrote the README** (entry 18). It leads with the score **and with
  the fact that it is under the baseline**, repeats `n = 102` with the ten
  omnizon exclusions beside every rate, gives both halves, and spends its length
  on the three findings that make 17.6% defensible rather than on softening it.
  Every figure in it was traced to a numbered entry and **three untraceable
  counts were deleted rather than cited loosely**. The placeholder check ran with
  two controls, both of which fired.
- **Nothing is next.** The feature list is exhausted. What remains open is
  recorded in `progress.md` under *What's Next* as open work, not planned work:
  the designed same-manifest-twice variance run, `rich` above a 12 000-token
  observation budget, and omnizon if the takedown lifts. Each is a new
  measurement with its own entry, not an edit to an existing number.
- **Branch / commit:** `main`, tracking `origin/main` at
  `github.com/sarthakydv/web-agent-eval` (**public**). CI green.

## Completed This Session (`feat-007` — the ablation and the cap)

- [x] **`runs/rich102/`** — 102 tasks at `rich`, caps identical to `full102`,
      111.6 min, one round, supervisor **exit 0**, **zero provider errors**.
      `passed 23 / failed 19 / capped 60`. **22.55%.**
- [x] **`runs/cap50/`** — the 56 tasks `full102` ran out of steps on, and only
      those, at **50 steps / 800 000 tokens / 600 s**, its own frozen manifest,
      67.0 min, **exit 0**, zero provider errors. **3 converted, 40 still
      capped**, all 40 on the step cap.
- [x] **The level is a frozen manifest field.** `manifest.ensure` refuses a
      resume that contradicts it; `run_batch.py` takes the level from the
      manifest rather than its own flag, so a half-lean half-rich run cannot be
      produced by mistyping a command. Manifests predating the field read as
      unrecorded, so `full102` stays resumable and `supervise.py` idempotent.
- [x] **`scripts/ablation.py`** — refuses to print a delta until it has proved
      from the two manifests that the runs differ in exactly one thing. Both
      modes: `arms` (the ablation) and `cap` (cap sensitivity). Includes an
      exact two-sided McNemar test on the discordant pairs, because the arms are
      paired and the totals are not the informative quantity.
- [x] **`scripts/cap_budget.py --max-steps N`** — re-derives the token cap at a
      new step budget and prints the per-step allowance. At 50 steps the old
      400 000-token cap has **headroom 0.55x and the script exits 1**: doubling
      the step cap alone would have let the token cap fire first.
- [x] **`scripts/preflight.py`** handles an explicit task subset and checks the
      level, so a subset run's manifest still names every id and every exclusion.
- [x] **`tests/test_ablation.py`** — 24 tests. Seven comparability refusals, each
      with the case where it must **not** fire beside it. 181 in total.
- [x] **`docs/DECISIONS.md` entry 17**, `README.md` updated so the 25-step cap
      is stated beside the rate and the ablation's null result is not rounded up.

## Completed Earlier (`feat-006` — the full 102-task run)

- [x] **The run.** `runs/full102/`, 2026-07-31 06:58 → 08:14 UTC, 102 tasks,
      concurrency 3, supervisor **exit 0** — every manifest task has a terminal
      record. `passed 18 / failed 26 / capped 56 / errored 2`, 10 excluded.
      **17.6% over n = 102.** Neither budget was approached: 4.00 M of 8 M
      tokens, 76 min of 180.
- [x] **`src/web_agent_eval/sites.py`** — reachability for every replica host,
      three probes each, URLs read from the installed task configs rather than
      copied. A 451, a 5xx, a DNS failure and a timeout are all "not reachable";
      a 308 landing on 200 is reachable, which is what gocalendar does.
- [x] **`scripts/preflight.py`** — the only thing that writes a manifest for a
      real run. Asserts the judge **and its control**, makes one live judge call,
      probes reachability and **freezes it into the manifest**, records the
      *served* model beside the requested one, then re-reads the manifest from
      disk and checks population, n, exclusion count and reason, sites,
      concurrency, served model and date. Refuses to write anything if a check
      fails, and refuses to overwrite an existing manifest.
- [x] **`scripts/run_batch.py` refuses a real run whose manifest has no
      reachability record**, so the preflight is structural, not remembered.
- [x] **Entry 7's site rule is now instrumented** — `RoundResult.site_*` counts
      reordered launches, task-positions passed over, idle-slot stretches and the
      worker-seconds they cost, printed per round by the supervisor.
- [x] **`scoring.subset_rates` / `subsets`** — the `jmespath` and judge-scored
      halves, rendered beside the headline. Derived from rows the payload already
      had, so the digest is unchanged and `feat-005`'s pilot still `--check`s.
- [x] **`tests/test_preflight.py`** — 11 tests, each with its control: a 451/5xx/
      DNS failure must read as unreachable *and* a 200 and a 308→200 must not; the
      new manifest fields must round-trip *and* a pre-`feat-006` manifest must
      still load; the site rule must bill idle slots on same-site work *and* bill
      nothing when the sites differ.
- [x] **`docs/DECISIONS.md` entry 16**, `README.md` headline filled in.

## Completed Earlier (`feat-005` — evaluation and cost recording)

- [x] **`src/web_agent_eval/judge.py`** — the judge, asserted and instrumented.
      `require()` refuses to run if `OPENAI_API_KEY` is absent or if
      `OPENAI_BASE_URL` would send REAL's judge anywhere but `api.openai.com`.
      The instrumentation does **not** reimplement agisdk's judge: the real
      `generate_from_model` runs verbatim and is only wrapped to mark a window,
      with `openai`'s `Completions.create` recording any call made inside it. So
      the base URL in every record is the one the HTTP client really used.
- [x] **`src/web_agent_eval/scoring.py`** — the aggregate, from `manifest.json`
      and `records/*.json` and nothing else. Two cost columns, a digest over
      every per-task row, and "judged" counted apart from "never judged".
- [x] **`scripts/judge_probe.py`** — the endpoint assertion, its control, and one
      task end to end with the judge call printed.
- [x] **`scripts/score.py`** — `--check` recomputes and fails on any drift.
- [x] **`scripts/project_run.py`** — `feat-006`'s runtime and cost, projected
      from the pilot with the arithmetic printed rather than asserted.
- [x] **`batch.real_episode` asserts and instruments the judge per episode**, and
      the terminal record carries the judge ledger — so the aggregation can read
      records alone. `scripts/run_batch.py` asserts it once more before the first
      browser starts.
- [x] **20 new tests** (`tests/test_judge.py`, `tests/test_scoring.py`), none of
      which start a browser, make a network call or need a real key: the openai
      call is stubbed *underneath* agisdk so agisdk's own code path executes.
      146 in total.

## The judge, proven rather than assumed

Two failure modes look exactly like success, and both were ruled out explicitly.

**Misrouted judge.** `OpenAI()` takes no arguments in agisdk, so it reads
`OPENAI_BASE_URL`. Asserted: `base_url='https://api.openai.com/v1/'`,
`host='api.openai.com'`, `model_default='gpt-4.1'` (read from
`WebCloneEvaluator.__init__`'s signature, not copied here). **Control:**
`OPENAI_BASE_URL` set to z.ai → `JudgeMisrouted`, refused.

**Judge never called.** `agisdk`'s `validate()` only evaluates once the agent has
sent a message, so a capped episode that never answered gets `reward = 0.0` from
a path where `evaluate()` never ran. `evaluate()` calls and judge calls are
counted separately. `v1.dashdish-1` → `evaluate_calls=1, judge_calls=1`, served
`gpt-4.1-2025-04-14`, `usage prompt=140 completion=3`, reply `'1.0'`,
`similarity=1.0`, `is_correct=True`. Control `v1.gomail-2` (no `llm_boolean`
eval) → `evaluate_calls=0, judge_calls=0`.

**`gpt-4.1` is served as `gpt-4.1-2025-04-14`.** The alias resolves to a dated
snapshot and OpenAI names it in the response — the opposite of entry 9's z.ai
case, where `glm-5.1` was answered by `glm-5.2` with no way to pin it. What is
recorded is the served string.

## The pilot, and what it says about `feat-006`

10 tasks, one per reachable site, 5 judged and 5 not, at concurrency 3. **Chosen
for coverage, so its 4/10 is not a success rate** — same discipline as
`feat-004`'s 11 episodes.

| | measured |
|---|---|
| round | 10/10 terminal in **287.0 s**, 0 provider errors |
| statuses | 4 passed, 2 failed, **4 capped on the 25-step cap** |
| agent tokens | **344 473** total; mean 34 447, min 2 218, max 79 190 |
| judge | 4 calls, 601 prompt + 12 completion tokens = **$0.001298** |
| not judged | `v1.fly-unified-1` — needed the judge, capped without answering |

Projected to `n = 102`: **~3.51M agent tokens**, **~48.8 min** at concurrency 3,
judge ceiling **$0.0191** over 59 `llm_boolean` evals across 55 tasks. Capped
episodes cost an order of magnitude more than passing ones, so **the cap rate is
the dominant term and the one 10 tasks measures worst** — re-check it after
`feat-006`'s first round. Entry 15 shows every multiplication.

## From `feat-004`: the published concurrency limit does not apply to this key

Run **before any batch code was written**, as entry 7 requires.

| Probe | Result |
|---|---|
| Burst, simultaneous completions at N = 2, 3, 4, 5, 6, 8, 10, 12 | **every one accepted, none rejected**, latency flat |
| Sustained, 3 workers, one call each per 4 s, 7 minutes | **315 calls, 315 ok, 0 rejected**, no latency drift |

z.ai publishes a concurrency limit of 3 for `glm-4.6`; that is the pay-as-you-go
figure and this is a Coding Plan key, which entry 4 already proved is a different
product. No `x-ratelimit-*` headers are exposed, so load is the only instrument.

**What it rules out:** a limit of 3, and any quota inside 315 calls / 7 minutes.
**What it does not:** a quota at hour two. A full 47-task run is only of order
500–1 000 model calls, so probing that far would cost as much as the run it
protects. The answer to the residual risk is structural, not a bigger probe —
a provider error is non-terminal, the supervisor exits 1 as stalled rather than
filling the manifest with zeros, and the run resumes.

**The default stays 3.** The measurement lifted the provider constraint, not the
site rule or comparability. Raising it is a human scoping decision — entry 12.

## From `feat-004`: the rule that was not in entry 7 — retire a capped worker

`feat-003`'s wall-clock cap is `future.result(timeout=...)` on the episode's own
worker thread. That bounds the **wait**, and Python cannot kill a thread — so
when the cap fires the thread is **abandoned, not terminated**, and may still be
driving a browser. REAL scores by **diffing environment state**, so letting that
process take another task would contaminate the next task's diff and produce a
*silently wrong score*: the exact class of error entry 7 exists to prevent.

- **One process per task** — reuse is structurally impossible.
- **A `wall_clock` cap gets a 1 s grace, then `SIGKILL`**, where a normal worker
  gets 10 s to exit on its own.
- **Its site stays reserved until the process is confirmed dead.**

Verified by breaking it: removing the kill fails the test in 3.6 s
(`'killed': False`), **and then `pytest` itself cannot exit**, because
`multiprocessing` joins non-daemon children and the abandoned thread keeps the
child alive for its full hour. The hang is the bug.

## Verification Evidence

| Check | Command | Result |
|---|---|---|
| **(1) tests** | `uv run pytest -q -k 'resume or supervise'` | `50 passed, 76 deselected in 118.18s` |
| **(2) kill** | 6-task batch `SIGKILL`ed with 2 records down and 3 workers in flight, then restarted with the identical command | restart: `2 of 6 already terminal (skipping them)`, re-ran none, both records **byte-identical** (sha256), `EXIT 0` |
| **(3) stall** | same command with `ZAI_BASE_URL=…/paas/v4/` (entry 4's real 429) | `EXIT 1 (STALLED)`, **no `records/` directory at all**, 4 non-terminal `provider_error` rows |
| **(4) budget** | `--budget-tokens 60000` on a 6-task run | `EXIT 2 (BUDGET)` mid-run at 85 589 tokens, 3 terminal records intact |
| no-op | `supervise.py` again on the completed run | `already complete — nothing to do`, content+mtime digest **identical** |
| Lint | `uv run ruff check .` | `All checks passed!` |
| Full path | `./init.sh` | `126 passed`, `=== All checks passed ===` |

**Every check has its control**, per the standing rule — a supervisor that always
exits 1 passes the stall test:

| Check | Control — must NOT fire | Result |
|---|---|---|
| resume | a fresh run | `0 of 6 already terminal`, runs all six |
| stall | the same tasks on the working endpoint | `EXIT 0`, 2 terminal records |
| budget | the same run resumed at 400 000 tokens | `EXIT 0`, finishes |
| tests | three rules broken on purpose | each turns the suite red (below) |

### `feat-005`'s checks

| Check | Command | Result |
|---|---|---|
| **(1) endpoint** | `uv run python scripts/judge_probe.py` | `host api.openai.com`, `is_openai True`, `model_default gpt-4.1`, `OPENAI_BASE_URL_env None` |
| **(1c) control** | same, with `OPENAI_BASE_URL` set to z.ai | `JudgeMisrouted` — refused, naming the host |
| **(2) judge runs** | `... --task v1.dashdish-1` | `evaluate_calls=1`, `judge_calls=1`, served `gpt-4.1-2025-04-14`, `prompt=140 completion=3`, reply `'1.0'`, `similarity=1.0` |
| **(2c) control** | `... --task v1.gomail-2` (no `llm_boolean` eval) | `evaluate_calls=0`, `judge_calls=0` |
| **(3) pilot** | `supervise.py --run-id pilot --population explicit --tasks <10> --concurrency 3` | `10/10 terminal`, `344473 tokens`, `{"capped": 4, "failed": 2, "passed": 4}`, `EXIT 0` |
| **(4) reproduces** | `score.py --run-id pilot --check`, twice | same digest `7e674db6…`, exit 0 both times |
| **(4c) control** | same, on a copy with one `status` flipped | `RECOMPUTED SCORE DIFFERS`, exit 1, five fields named |
| **(5) tests** | `uv run pytest -q tests/test_judge.py tests/test_scoring.py` | `20 passed in 1.84s` |

### Three deliberate breaks (`feat-004`), to prove the suite is not vacuous

| Break | Result |
|---|---|
| remove the `SIGKILL` that retires a capped worker | fails in 3.6 s on `'killed': False`, then `pytest` will not exit |
| ignore existing terminal records (resume off) | `assert 0 == 3` (skipped), and a record file is overwritten by attempt 2 |
| classify a 429 as a task failure | `assert {'errored': 1} == {'provider_error': 1}` |

### Three more (`feat-005`), on the new suite

| Break | What it models | Result |
|---|---|---|
| patch `utils.generate_from_model` | instrumenting a reference nobody calls — `evaluate.py` imported its own | 3 failed, 9 passed; `assert 0 == 1` |
| drop the judge-window guard in `Completions.create` | the agent's own z.ai calls counted as judge tokens | 1 failed; `assert 1 == 0` |
| give the agent a dollar figure too | the two cost columns summed into one | 1 failed; `assert 0.000882 is None` |

And the reproducibility check has its own control: a copy of `runs/pilot` with
one task's stored `status` flipped `passed -> failed` makes `score.py --check`
exit 1 naming `counts, passed, rate_over_manifest, rate_over_terminal, tasks`.
Editing one token count — which leaves the rate identical — also changes the
digest, and that is a test.

## From `feat-004`: 11 real episodes, and they are not a success rate either

4 passed, 4 failed, 3 capped — over task sets chosen to exercise the mechanics,
`n = 11`, population `explicit`. **It must never be quoted as a score.** Two
things in it are worth `feat-006`'s attention:

- **Every cap that fired in a live episode was the 25-step cap**, at the `lean`
  level. One episode spent 74 918 tokens; the range was 8 940 – 74 918 tokens
  and 23.5 – 109 s at concurrency 2–3 (and per entry 7 a per-task wall clock at
  N > 1 is not comparable to a sequential one).
- **No wall-clock cap fired in a real run**, so the abandoned-thread rule is
  verified against a fake that reproduces the condition exactly
  (`tests/fake_episodes.py`, `v1.wedge-*`), not a live browser hang.

## Decisions Made

Entries 13, 14 and 15 were appended this session; 1–12 predate it.

13. **`feat-005`: the judge really runs, and the reachable population is 102.**
    The endpoint assertion and its control; one task end to end with the judge
    call observed; the alias-to-snapshot finding; the "never judged" counter and
    why it is separate; the 112 / 10 / 60 / 55 / 47 arithmetic asserted against
    the installed task set; the three deliberate breaks; and a second, harder
    reason for one process per task (Playwright's cached sync driver is bound to
    the thread that started it).
14. **Cost has two halves, and they are not the same kind of number.** Agent
    tokens with no dollar figure — z.ai publishes no rate for this Coding Plan
    key — beside judge dollars from a published rate times measured `usage`,
    carrying the rate's retrieval date. They are never summed, and a test
    enforces it.
15. **`feat-006` projected from a pilot that ran, with the arithmetic shown.**
    The pilot table, the reproducibility check and its control, and the
    projection to `n = 102` with its caveats and a budget recommendation.

## Blockers / Risks

- **The denominator is 102, never 112.** `evals-omnizon.vercel.app` is
  DMCA-taken-down (451), re-confirmed before *and* after the run. The count and
  reason must be published beside any rate — entries 5 and 16.
- **The 429 is real and it will come back.** `429 / code 1302` at seventeen
  minutes into the run, which entry 12's probes had said they could not rule out.
  The design survived it and no task was mislabelled, but a longer run should
  expect it: concurrency halves on each one and recovers one worker per five
  clean episodes, so a burst costs wall clock rather than correctness.
- **Never quote a rate re-run to improve it.** The 5 provider-error tasks were
  retried because a `429` is not a task failure; every task still has exactly one
  terminal attempt, and the rate is the first-terminal-attempt rate. Re-running
  a *failed* task would break that, and nothing in the tooling stops a human
  from doing it by hand.
- **A misrouted judge would look exactly like a working one.** The assertion now
  runs before every batch and refuses on failure, but the risk lives in the
  environment. Never export `OPENAI_BASE_URL`, and never uncomment it in `.env`
  except for entry 10's optional GLM-as-judge comparison, which must opt in.
- **The cap rate came in at 54.9%, not the pilot's 40%.** That was the
  projection's dominant term and its weakest input, and it moved 15 points —
  which is most of why the run took 76 minutes rather than 48.8.
- **Whether 25 steps at the `lean` level is the right operating point** is
  `feat-007`'s question, and it is now the interesting one: **more than half the
  population never finished**. Caps are held constant across arms (entry 11), so
  changing them is a new measurement, not an edit to this one.
- **Replica sites are easier than live ones.** A score here is not comparable to
  a live-web score.

## Next Session Startup

1. Read `AGENTS.md`, then the index at the top of `docs/DECISIONS.md`. **There
   is no next feature** — the list is exhausted — so start from `README.md`,
   which states every published number with the entry it comes from. Entries 16
   and 17 hold the measurements, 18 holds the audit that put them in the README,
   and 1 holds the claim this project does not make. Neither `feature_list.json`
   nor `docs/DECISIONS.md` is read end to end.
2. Run `./init.sh` — expect `181 passed` and all checks passed. It takes ~2½
   minutes: `feat-004`'s and `feat-006`'s tests spawn real worker processes.
3. If the browser is missing: `uv run playwright install chromium` (agisdk pins
   Chromium build 1228; a mismatch fails with an error that does not look like a
   version problem).

Nothing is outstanding. `main` is the only local branch and `main == origin/main`.
`runs/` is gitignored, so `runs/full102/`, `runs/rich102/` and `runs/cap50/` are
**local only** — their numbers live in entries 16 and 17 and in the evidence
fields of `feat-006` and `feat-007`. If those directories are lost the runs
cannot be re-derived; they can only be re-run, and a re-run is a new
measurement — which `feat-007` now quantifies: **17.9% of episodes land
somewhere materially different on a re-run at `temperature=0`.**

## Recommended Next Step

**None. All eight features are done and the README is written.** If this repo is
picked up again, the three qualifiers that must survive any edit to it are:

- **17.6% is at a 25-step cap**, and the cap was tested rather than assumed:
  3 of 56 capped tasks convert at 50 steps, 40 still stall. Entry 17.
- **Replica sites are easier than live ones.** A score here is not comparable to
  a live-web score, and that travels with every number.
- **A five-task delta is noise here.** The measured run-to-run flip rate is
  17.9%, so the richness ablation's +4.9 points is "no effect detected", not a
  small win — and no summary may upgrade it.

Two further rules the README now depends on: **every figure in it resolves to a
numbered DECISIONS entry** (the map is in entry 18 — a new number means a new
entry first), and **`n = 102` with the ten omnizon exclusions is stated beside
every rate**, never a bare percentage.

The one thing `feat-007` deliberately left undone: a **designed** variance run —
the same manifest twice at the same caps — which would turn that 17.9% from an
accidental measurement into a stated one. It is a new measurement, not an edit
to an existing one, and the README names it as open rather than dropping it.

How to start any new run — the preflight is not optional:

```
uv run python scripts/preflight.py  --run-id <id> --population 102 --concurrency 3
uv run python scripts/supervise.py  --run-id <id> --population 102 --concurrency 3 \
    --budget-tokens 8000000 --budget-wall-clock-s 10800
uv run python scripts/score.py --run-id <id>
uv run python scripts/score.py --run-id <id> --check
```

- **Expect ~76 minutes and ~4M agent tokens** at concurrency 3 with a judge bill
  under a cent — measured, not projected. Budget headroom is deliberate: exiting
  2 on a budget is a stop, not a failure.
- **`preflight.py` writes the manifest and nothing else does.** `run_batch.py`
  refuses a real run whose manifest has no reachability record.
- **Take a postflight probe too.** The before-probe alone cannot tell you a host
  died mid-run; only the pair can.
- **`score.py` reads records only**, so the published figure can be re-derived
  from `runs/<id>/` months later. Run `--check` before quoting anything.
- **An arm's rate is only comparable to entry 16's if the caps and the population
  match.** Change one thing.
- **Publish `n = 102` with the 10 omnizon exclusions and their reason**, state it
  against REAL's published **≤41%** baseline, and count `capped` separately from
  `failed` — "k ended on a cap" is a different statement from "the agent failed
  k" (entry 7).
- **Name the models**: agent `glm-4.6`, scorer `gpt-4.1` as served
  (`gpt-4.1-2025-04-14` on 2026-07-31). Entry 13.
- **Re-check the cap rate after round 1.** It drives the projection more than
  anything else.
