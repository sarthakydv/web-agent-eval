# Session Handoff — web-agent-eval (P3)

## Current Objective

- **Goal:** Measure a web agent on REAL (112 tasks, 11 deterministic replica
  sites) with every number traceable to something that actually ran.
- **Current status:** `feat-001` `[GATE]` **passed**, `feat-002` … `feat-005`
  **done**. One REAL task ran end to end on GLM and scored **1.0**; the
  serializer renders an observation at a parameterised richness level under a
  measured token budget; the episode loop runs under three independent caps; the
  batch runner and supervisor drive it unattended, resuming after a `SIGKILL`,
  refusing to call a `429` a task failure, and stopping on a budget; and
  **scoring and cost recording are done** — REAL's own `gpt-4.1` judge has been
  seen to run against OpenAI and return a grade, and a 10-task pilot's aggregate
  reproduces from the stored records alone.
- **The reachable population is 102, not 47.** The judge works, so all 102
  reachable tasks are scorable: 55 by `gpt-4.1`, 47 by `jmespath` checks. Only
  the 10 omnizon tasks are out, and their count and reason travel with the rate.
- **Next is `feat-006`, and it is deliberately not started.** It is the long
  unattended run and a human should decide when it begins. It is now scheduled
  against a measurement, not a hope — entry 15.
- **Branch / commit:** `main`, tracking `origin/main` at
  `github.com/sarthakydv/web-agent-eval` (**public**). CI green.

## Completed This Session (`feat-005` — evaluation and cost recording)

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

- **`feat-006` is not started on purpose.** It is the long unattended run — about
  **49 minutes** at concurrency 3 — and a human should decide when it begins. It
  is not blocked; it is waiting.
- **`feat-006`'s denominator is 102, never 112.** `evals-omnizon.vercel.app` is
  DMCA-taken-down (451). The count and reason must be published beside any rate —
  entry 5.
- **A misrouted judge would look exactly like a working one.** The assertion now
  runs before every batch and refuses on failure, but the risk lives in the
  environment. Never export `OPENAI_BASE_URL`, and never uncomment it in `.env`
  except for entry 10's optional GLM-as-judge comparison, which must opt in.
- **The cap rate is the projection's dominant term and its weakest input.** 4 of
  10 pilot episodes capped on 25 steps, and a capped episode costs an order of
  magnitude more than a passing one. If `feat-006` caps at 60% the token total
  moves toward 5M; at 20% toward 2.5M. Re-check after round 1.
- **A quota beyond 315 calls / 7 minutes is not ruled out.** The design survives
  it (non-terminal provider errors, stall exit, resume) but a long unattended run
  should be checked on rather than assumed.
- **Whether 25 steps at the `lean` level is the right operating point** is
  `feat-006`'s and `feat-007`'s question, not something to change quietly
  mid-measurement — caps are held constant across arms (entry 11).
- **Replica sites are easier than live ones.** A score here is not comparable to
  a live-web score.

## Next Session Startup

1. Read `AGENTS.md`, then **only `feat-006`'s entry** in `feature_list.json`,
   then the index at the top of `docs/DECISIONS.md` — entry 7 for the run loop's
   rules, 5 for the population, 12 for how a run is driven, 13–15 for the judge,
   the two cost columns and the projection. Neither file is read end to end.
2. Run `./init.sh` — expect `146 passed` and all checks passed. It takes ~2
   minutes: `feat-004`'s tests spawn real worker processes.
3. If the browser is missing: `uv run playwright install chromium` (agisdk pins
   Chromium build 1228; a mismatch fails with an error that does not look like a
   version problem).

Nothing is outstanding. `main` is the only local branch and `main == origin/main`.
`runs/` is gitignored, so `runs/pilot/` is local only — its numbers live in
entry 15 and in `feat-005`'s evidence field.

## Recommended Next Step

`feat-006`, the full run, **when a human starts it**. Everything it needs is
measured:

```
uv run python scripts/supervise.py --run-id <id> --population 102 \
    --concurrency 3 --budget-tokens 8000000 --budget-wall-clock-s 10800
uv run python scripts/score.py --run-id <id>
uv run python scripts/score.py --run-id <id> --check
```

- **Expect ~49 minutes and ~3.5M agent tokens**, with a judge bill near two
  cents. Both budgets above sit above the pessimistic bound rather than the
  central estimate, because exiting 2 on a budget is a stop, not a failure.
- **The run asserts its judge before the first browser starts** and refuses if it
  would go anywhere but OpenAI. That line is in the log; read it.
- **`score.py` reads records only**, so the published figure can be re-derived
  from `runs/<id>/` months later. Run `--check` before quoting anything.
- **Publish `n = 102` with the 10 omnizon exclusions and their reason**, state it
  against REAL's published **≤41%** baseline, and count `capped` separately from
  `failed` — "k ended on a cap" is a different statement from "the agent failed
  k" (entry 7).
- **Name the models**: agent `glm-4.6`, scorer `gpt-4.1` as served
  (`gpt-4.1-2025-04-14` on 2026-07-31). Entry 13.
- **Re-check the cap rate after round 1.** It drives the projection more than
  anything else.
