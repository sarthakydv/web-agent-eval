# Progress — web-agent-eval (P3)

## Current State

**Last Updated:** 2026-07-31
**Active Feature:** none — `feat-001` … `feat-005` are done, next is `feat-006`
**Status:** the `[GATE]` is through (one REAL task scored **1.0**), the
observation serializer exists with richness as a parameter and a measured token
budget, the **episode loop is built and bounded**, the **batch runner and
supervisor are proven against a real SIGKILL, a real 429 and a real budget
overrun**, and **scoring and cost recording are done**: REAL's own `gpt-4.1`
judge has been seen to run against OpenAI and return a grade, a 10-task pilot
produced per-task pass/fail and per-task tokens, and the aggregate reproduces
from the stored records alone. **The reachable population is 102, not 47.**
`feat-006` — the long unattended run — is next and is **left for a human to
start**. The repo is **public** at `github.com/sarthakydv/web-agent-eval` with
CI green.

## Status

### What's Done

- [x] Python pinned to **3.12.12** via `uv`; `agisdk` **0.3.5** from PyPI
      installs and imports; `REAL.harness` is callable.
- [x] `./init.sh` runs environment checks, `ruff` and `pytest`, and fails loudly.
      **Proven non-vacuous:** on its first run it caught a real `ruff` error
      (`PLW1510`, `subprocess.run` without `check`) and failed the build until
      it was fixed.
- [x] `docs/DECISIONS.md` entries 1–3 written **before any feature exists**.
- [x] **`feat-001` [GATE] passed.** `v1.gomail-2` on `glm-4.6` via z.ai:
      `cum_reward = 1.0`, 9 steps, 35.4 s, 20 931 tokens. All three questions
      answered with recorded output — `docs/DECISIONS.md` entry 4.
- [x] 8 tests passing (3 environment, 5 action extraction).
- [x] **`feat-002` done.** `src/web_agent_eval/observation.py` renders an agisdk
      observation as text at a parameterised richness level. Two levels ship
      (`lean`, `rich`); a caller-defined level needs no change to `serialize()`,
      which is what `feat-007` requires. `docs/DECISIONS.md` entry 6.
- [x] **Fixtures are real captures.** The gate persisted no observation — its
      run directories hold summaries and logs only — so five were captured
      fresh from live runs on two sites and committed under
      `fixtures/observations/` (DOM snapshot, accessibility tree, element
      properties, 1280x720 PNG).
- [x] **Token budget: 12 000 provider tokens, enforced locally at 11 741.**
      Counted with `tiktoken`/`cl100k_base` and checked against z.ai's own
      `prompt_tokens` on 10 real calls: local understates by 1.5% aggregate,
      2.2% worst case. Largest provider-side rendering measured: 11 979.
- [x] **`feat-003` done.** `src/web_agent_eval/episode.py` is the loop:
      observe, decide, act, terminate, under three independent caps
      (`caps.py`), with a GLM policy (`policy.py`) and a thin agisdk env
      adapter (`environment.py`). `docs/DECISIONS.md` entry 11.
- [x] **The wall-clock cap bounds the step itself, not the gap between steps.**
      Every operation runs on the episode's own worker thread and is awaited
      with the time left on the episode deadline, so a hanging step costs the
      budget and not a minute more. The test asserts on **elapsed time**:
      20 s of faked hang against a 0.2 s budget returns in under 2 s.
- [x] **Cap values, derived not guessed.** 25 steps / 400 000 provider tokens /
      300 s. `uv run python scripts/cap_budget.py` derives the token cap from
      the worst honest episode (354 350) and reports the headroom (1.13x); a
      cap that bit on the rich arm and not the lean one would confound
      `feat-007`.
- [x] **The token cap is enforced on z.ai's own `usage`**, falling back to a
      local count marked up by entry 6's measured 2.2% undercount only when a
      response arrives without one. The record keeps the two apart.
- [x] **Every episode records why it ended** — `completed`, `capped` (which cap,
      what limit, what observed value) or `errored`. Nothing escapes to the
      caller; a cap is never an exception.
- [x] **Safe for three concurrent episodes in three processes** (entry 7's
      limit). No module-level mutable state, no cached singletons, per-episode
      clocks and counters, caller-supplied output paths, task id on every log
      line. Two concurrent episodes against fakes are asserted independent.
- [x] **`feat-004` done.** `src/web_agent_eval/{manifest,records,batch,cli}.py`
      plus `scripts/{run_batch,supervise}.py`: a batch runner that resumes and a
      supervisor that stops on one of three machine-checkable conditions.
      `docs/DECISIONS.md` entry 12.
- [x] **The concurrency limit was measured, and the published 3 is wrong for
      this key.** `scripts/concurrency_probe.py`: 2, 3, 4, 5, 6, 8, 10 and 12
      simultaneous completions were **all accepted, none rejected**, and a
      sustained 3-worker probe at the run's own cadence (one call per 4 s per
      worker) ran **315 calls over 7 minutes with zero rejections and no latency
      drift**. z.ai's published 3 is a pay-as-you-go figure; this is a Coding
      Plan key (entry 4). **The default stays 3** — the site rule and
      comparability, not the provider, are what bind now, and raising it is a
      human scoping decision.
- [x] **A worker whose wall-clock cap fired is SIGKILLed and never reused.**
      Python cannot kill a thread, so a fired cap leaves the episode's worker
      thread *abandoned, not terminated*, possibly still driving a browser. REAL
      scores by diffing environment state, so reusing that process would
      contaminate the next task's diff and produce a silently wrong score. One
      process per task, killed after a 1 s grace on a `wall_clock` cap, and its
      site stays reserved until it is confirmed dead — entry 12.
- [x] **Killed and resumed for real.** A 6-task batch was SIGKILLed with 2
      records on disk and 3 workers in flight; the restart reported `2 of 6
      already terminal (skipping them)`, re-ran none of them, left both records
      byte-identical (sha256 checked), and exited 0.
- [x] **A provider outage produces zero terminal records.** Pointed at the 429
      endpoint, the supervisor exited 1 as stalled with **no `records/`
      directory at all** and four non-terminal `provider_error` rows. The
      control — the same tasks on the working endpoint — exited 0.
- [x] **A budget the run cannot meet exits 2 mid-run** with every already
      terminal record intact; resumed with a budget it can meet, the same run
      exited 0.
- [x] 126 tests passing; all of them run with no browser, no network and no
      API key.
- [x] **The tracker enforces its own rules, and each was tested by breaking it.**
      `init.sh` fails on a feature with no `verification` command, a `done`
      feature with empty `evidence`, and more than one feature `in-progress`. All
      three were broken deliberately in a scratch copy and confirmed to exit 1
      naming the problem — entry 8. `ci.yml` holds a second copy of the same
      logic, also tested against the same three broken files.
- [x] **CI runs the offline half of `init.sh`** on every push and PR — no key, no
      browser, no network. First run green in 21 s.
- [x] **Repo is public** at `github.com/sarthakydv/web-agent-eval`. Pre-push
      scans confirmed no key and no `.env`/credential blob anywhere in history,
      including inside the gzipped and PNG fixtures — entry 8.

- [x] **`feat-005`: the judge runs, and it runs against OpenAI.** `OPENAI_API_KEY`
      is filled. The endpoint is asserted before any run starts and the run
      refuses if it is wrong; the assertion was broken on purpose with
      `OPENAI_BASE_URL` pointed at z.ai and confirmed to refuse. One
      `llm_boolean` task ran end to end with the judge call observed —
      `base_url='https://api.openai.com/v1/'`, requested `gpt-4.1`, served
      `gpt-4.1-2025-04-14`, 140 prompt + 3 completion tokens, reply `'1.0'` —
      entry 13.
- [x] **The reachable population is 102, not 47.** 55 of the 102 are graded by
      `gpt-4.1`, the other 47 by `jmespath` checks, and the arithmetic is
      asserted against the installed task set rather than restated — entry 13.
- [x] **A 10-task pilot, one per reachable site, produced per-task pass/fail and
      per-task tokens**, and the aggregate reproduces from
      `runs/pilot/records/` alone. A copy with one status flipped fails the
      check — entry 15.
- [x] **Cost has two columns and they are never summed** — agent tokens with no
      dollar figure (z.ai publishes no rate for this Coding Plan key), judge
      dollars from a published rate times measured usage, with the rate's date —
      entry 14.

### What's In Progress

- Nothing. Stopped after `feat-005` as instructed, before `feat-006`.

### What's Next

1. **`feat-006` is the long unattended run, and a human decides when it starts.**
   Everything it needs is measured: population `102`, roughly **49 minutes** of
   wall clock at concurrency 3 and **~3.5M agent tokens**, with a judge bill of
   about **two cents** — entry 15 shows the arithmetic.
2. The command is `uv run python scripts/supervise.py --run-id <id>
   --population 102 --budget-tokens 8000000 --budget-wall-clock-s 10800`. It
   resumes on its own after any interruption and is a no-op once complete.
3. Score it with `uv run python scripts/score.py --run-id <id>`, then
   `--check` to confirm the published figure comes back out of the records.
4. `feat-006` must publish `n = 102` with the 10 omnizon exclusions and their
   reason beside the rate, and state it against REAL's published ≤41% baseline.

## Blockers / Risks

- [ ] **10 of the 112 tasks cannot run.** `evals-omnizon.vercel.app` returns
      HTTP 451 `DMCA_TAKEDOWN`. `feat-006`'s denominator is **n = 102** unless
      the site returns, and the count and reason must be published beside the
      rate — DECISIONS entry 5.
- [x] **60 of the 112 tasks are graded by an OpenAI judge, not by z.ai.**
      Answered by `feat-005`: the key is filled, the judge has been seen to run
      against `api.openai.com`, and **all 102 reachable tasks are scorable**.
      The judge's whole bill for the full run projects to about **$0.02**, so
      cost was never the real question — comparability was, and using REAL's own
      scorer settles it. Entries 13 and 14.
- [ ] **A misrouted judge would look exactly like a working one.** `OpenAI()`
      takes no arguments in agisdk and reads `OPENAI_BASE_URL`, so an exported
      value would send the judge to z.ai and GLM would grade GLM. Every run now
      asserts the endpoint before its first browser starts and refuses on
      failure — but the risk lives in the environment, not in this repo, so it
      stays listed. Never uncomment `OPENAI_BASE_URL` in `.env` except for
      entry 10's optional GLM-as-judge comparison, which must opt in explicitly.
- [ ] **A capped episode that never answered is a real zero but not a graded
      one.** agisdk's `validate()` only evaluates once the agent has sent a
      message. `v1.fly-unified-1` did exactly this in the pilot. It counts
      against the rate; it must not be described as the judge rejecting it.
      `score.py` names such tasks separately — entry 13.
- [ ] **Hosted, not local.** The sites are on Vercel; network latency stays.
      Round trips measured 0.13 s–2.37 s. The migration bought determinism, not
      speed — DECISIONS entry 4, Q2.
- [ ] **Replica sites are easier than live sites.** A score here is not
      comparable to a live-web score and must never be presented as one.

## Decisions Made

- **Benchmark is REAL; "unseen real sites" is no longer claimed** — entry 1.
- **Python pinned to 3.12**, `agisdk` from PyPI 0.3.5 — entry 2.
- **GLM reaches agisdk through `harness(agentargs=...)`, not `harness(model=...)`**
  — the built-in agent routes on model-name prefix and has no `base_url`
  parameter at all — entry 4.
- **The z.ai key is a Coding Plan key.** `api.z.ai/api/paas/v4/` returns 429; the
  working endpoint is `api.z.ai/api/coding/paas/v4/`. A bogus key returns 401,
  which is how we know it authenticates — entry 4.
- **Local scoring needs no leaderboard key** — entry 4, Q3.
- **Richness is a data object, not a branch.** `serialize(obs, level)` takes a
  `Richness`; `feat-007` varies that object and nothing else — entry 6.
- **Goal, URL and last-action error render at every richness level.** Dropping
  them would change the task rather than the richness — entry 6.
- **Tokens: local `cl100k_base` for budgets, provider `usage` for cost.** The
  local count was measured against z.ai's own and understates it by up to 2.2%;
  the budget absorbs that rather than ignoring it — entry 6.
- **A cap checked between steps is not a wall-clock cap.** The episode owns a
  deadline and every operation is awaited with the time left on it — entry 11.
- **The token cap is enforced on the provider's numbers**, with the measured
  2.2% markup applied only on the local fallback — entry 11.
- **Cap values are held constant across every arm** of `feat-006` and
  `feat-007`, because entry 9 measured reasoning spend scaling with the cap —
  entry 11.
- **When two caps cross at once the order is fixed**: wall clock, then tokens,
  then steps — entry 11.
- **`completed` is not `passed`.** The loop decides the two outcomes it honestly
  can and hands the reward to `feat-004`/`feat-005` for the rest — entry 11.
- **The manifest is frozen and a resume that contradicts it is refused.**
  Population, task ids, caps, model and entrypoint are the fields that decide
  what a run's number means; changing them under an existing run id is an error,
  not a quietly different experiment — entry 12.
- **A process that hit the wall-clock cap is retired, never reused**, and its
  site is held until it is confirmed dead — entry 12.
- **The attempt row is written before the terminal record**, so a kill in
  between leaves the task pending rather than done-with-no-trace — entry 12.
- **Rounds are numbered across restarts**, so a resumed run cannot overwrite the
  round file of the run it is resuming — entry 12.
- **Concurrency default stays 3 despite the probe.** The measurement removed the
  provider constraint; the site rule and comparability remain, and raising the
  default is a human scoping decision — entry 12.
- **The judge's endpoint is asserted, not assumed**, before any run starts, and
  a run whose judge would go anywhere but `api.openai.com` refuses to start —
  entry 13.
- **What is recorded is the model the server *served*.** OpenAI answered the
  `gpt-4.1` alias with `gpt-4.1-2025-04-14` and named the snapshot; entry 9's
  z.ai case did not. Both are recorded as served — entry 13.
- **"Judged" and "never judged" are counted apart.** A capped episode that never
  answered is a real zero, not a grade — entry 13.
- **Cost has two columns and they are never summed**: agent tokens with no
  dollars (no published rate for this plan), judge dollars from a published rate
  times measured usage, carrying the rate's date — entry 14.
- **A published figure must recompute from the stored records alone**, and the
  check compares a digest of every per-task row rather than the headline rate,
  which two different runs can share — entry 15.

## Files Modified This Session

`feat-005`, scoring and cost recording: `src/web_agent_eval/{judge,scoring}.py`
(new), `scripts/{judge_probe,score,project_run}.py` (new),
`tests/{test_judge,test_scoring}.py` (new, 20 tests),
`src/web_agent_eval/batch.py` (`real_episode` asserts and instruments the judge,
and the terminal record carries the judge ledger),
`src/web_agent_eval/manifest.py` (`judged_task_ids`, so the judge check and the
manifest's exclusion counts read one table), `scripts/run_batch.py` (asserts the
judge before the first browser starts), `feature_list.json`, `docs/DECISIONS.md`
(entries 13, 14, 15), `progress.md`, `session-handoff.md`. Nothing in
`feat-003`'s loop or `feat-004`'s round logic was changed.

Previous session — `feat-004`, the batch runner and supervisor:
`src/web_agent_eval/{manifest,
records,batch,cli}.py` (new), `scripts/{run_batch,supervise,concurrency_probe}.py`
(new), `tests/{test_resume,test_supervise,fake_episodes}.py` (new),
`feature_list.json`, `docs/DECISIONS.md` (entry 12), `progress.md`,
`session-handoff.md`. Nothing in `feat-003`'s loop was changed.

Previous session — `feat-003`, the episode loop: `src/web_agent_eval/{episode,caps,policy,
environment,action}.py` (new), `src/web_agent_eval/tokens.py` (added
`make_encoder`, the per-episode handle), `src/web_agent_eval/gate_agent.py`
(`extract_action` moved to `action.py`; it is not gate scaffolding and entry 6
says it lives on the action side), `tests/{test_caps,test_policy}.py` (new),
`scripts/cap_budget.py` (new), `feature_list.json`, `docs/DECISIONS.md`
(entry 11), `progress.md`, `session-handoff.md`.

Previous session — harness validation and first public push — **no feature work**, and `src/` and
`scripts/` were not touched: `feature_list.json` (a `verification` command on all
8 features, `verification_required`, `feat-004` widened to cover the supervisor,
`feat-006` required to name its population), `init.sh` (the three tracker rules),
`AGENTS.md` ("Feature list rules"), `docs/DECISIONS.md` (entries 7 and 8),
`.github/workflows/ci.yml` (new), `progress.md`, `session-handoff.md`.

Previous session: `src/web_agent_eval/{observation,tokens,fixtures}.py`,
`scripts/{capture_observations,render_observation,token_check}.py`,
`tests/{test_observation,test_tokens}.py`, `fixtures/observations/` (5 captures
plus screenshots), `pyproject.toml`, `.gitignore`, `feature_list.json`,
`docs/DECISIONS.md`, `progress.md`, `session-handoff.md`.

Earlier session: `src/web_agent_eval/{__init__,glm,gate_agent}.py`,
`scripts/run_gate.py`, `tests/test_gate_agent.py`.

## Evidence of Completion

- [x] Gate run: `cum_reward: 1.0`, `terminated: True`, `err_msg: None` on
      `v1.gomail-2`; full transcript in `feature_list.json`'s evidence field.
- [x] Serializer: `uv run python scripts/render_observation.py` → both levels of
      all five fixtures under budget; `rich` is 4x-6x `lean` on a loaded page.
- [x] Token count checked against the provider: `uv run python
      scripts/token_check.py` → `glm/cl100k` ratio 1.015 aggregate, 1.022 worst.
- [x] `feat-003` verification: `uv run pytest -q -k caps` → `25 passed, 51
      deselected in 1.31s`; each cap fires in isolation, each has a control that
      asserts it does *not* fire, and the wall-clock case asserts on elapsed
      time. Four deliberate breaks confirmed the suite is not vacuous — entry 11.
- [x] Cap derivation: `uv run python scripts/cap_budget.py` → worst honest
      episode 354 350 provider tokens against a 400 000 cap, 1.13x headroom.
- [x] `feat-004` verification, all four checks with their control cases:
      `uv run pytest -q -k 'resume or supervise'` → `50 passed, 76 deselected in
      118.18s`; a real batch SIGKILLed and restarted (skipped 2 of 6, re-ran
      none, records byte-identical, exit 0); a real 429 endpoint → exit 1 with
      **zero** terminal records; a 60 000-token budget → exit 2 mid-run with 3
      records intact, and the same run resumed at 400 000 → exit 0. Three
      deliberate breaks confirmed the suite is not vacuous — entry 12.
- [x] Concurrency probe: burst 2–12 all accepted, and 315 sustained calls over
      7 minutes at the run's cadence with zero rejections — entry 12.
- [x] `feat-005` verification, with its controls: the judge endpoint asserted
      (`host api.openai.com`, `model_default gpt-4.1`) and the assertion broken
      on purpose with `OPENAI_BASE_URL` set to z.ai → refused; `v1.dashdish-1`
      run end to end with **1 judge call**, `served gpt-4.1-2025-04-14`,
      `usage prompt=140 completion=3`, `reply '1.0'`, `similarity=1.0`; the
      `jmespath`-only control `v1.gomail-2` → **0 judge calls**; a 10-task pilot
      → `10/10 terminal, 344473 tokens, {"capped": 4, "failed": 2, "passed": 4}`;
      `score.py --check` reproduces the digest twice and **exits 1** on a copy
      with one status flipped. Three deliberate breaks turned the new suite red —
      entries 13, 14, 15.
- [x] `feat-006` projection from that pilot: `102 x 34,447.3 = 3,513,625` agent
      tokens, `102 x 28.70s = 2,928s = 48.8 min` at concurrency 3, judge ceiling
      `$0.0191` over 59 `llm_boolean` evals — entry 15.
- [x] Tests pass: `uv run pytest -q` → `146 passed in 114.80s`
- [x] Lint clean: `uv run ruff check .` → `All checks passed!`
- [x] Full path: `./init.sh` → `=== All checks passed ===`

## Notes for Next Session

**The pre-rewrite refs are gone.** `refs/original/*` and `backup-pre-rewrite` were
deleted, the reflog expired and `git gc --prune=now` run, after verifying that
every old commit was content-identical to its rewritten counterpart except the
root's one deleted line. `main` is the only local branch; a `git push --all` can
no longer publish anything unintended.

Setup gained one step: **`uv run playwright install chromium`**. `agisdk` pins
Chromium build 1228 and a mismatched build fails the run with an error that
looks nothing like a version problem.

`src/web_agent_eval/gate_agent.py` is still gate scaffolding and is now used by
nothing but `scripts/run_gate.py`. The project's agent is `policy.GlmPolicy`
driven by `episode.run_episode`; only `extract_action` survived from the gate,
and it moved to `action.py`.

`AgisdkEnvironment` does **not** run agisdk's `default_obs_preprocessor` — it
deletes `axtree_object` and `dom_object`, and the serializer's fallback to a
pre-flattened tree is not the richness level `feat-007` asked for. It also
leaves gym's `max_episode_steps` unset on purpose: the `TimeLimit` wrapper would
record a wrapper truncation as `completed`/`truncated` rather than `capped`.

`AgisdkEnvironment` has now been exercised for real: 11 live episodes ran across
`feat-004`'s checks. **That is not a success rate** — 4 passed, 4 failed, 3
capped on steps, over task sets chosen to exercise the mechanics, n = 11,
population `explicit`. It must never be quoted as a score.

Worth `feat-006`'s attention: **every cap that fired in a real episode was the
25-step cap**, at the `lean` observation level, and one episode spent 74 918
tokens. No wall-clock cap fired in a real run, so the abandoned-thread rule is
verified against a fake that reproduces the condition exactly
(`tests/fake_episodes.py`, `v1.wedge-*`) rather than a live browser hang.

Two accounting lines exist now and must never be mixed: **budget accounting** is
local `tiktoken` over a rendered observation; **cost accounting** (`feat-005`) is
the provider's `usage` field summed from real responses. Entry 4's 20 931 is the
second kind. Cost accounting now has **two providers in two columns** and they
are never summed — entry 14.

**One process runs one task, and there is now a second, harder reason.** Entry 12
gave the state-contamination reason. Building `feat-005`'s probe produced the
other: `agisdk` starts Playwright's *sync* driver once per process and caches it,
and the driver's greenlet dispatcher is bound to the thread that started it.
Every episode gets a fresh `BoundedRunner` thread, so a second episode in the
same process dies at `env.reset` with `greenlet.error: cannot switch to a
different thread (which happens to have exited)` — zero steps, zero tokens.
`batch.py` was already right; `scripts/judge_probe.py` now refuses a second
`--task` rather than reporting a fake failure. Entry 13.

**The pilot's 4/10 is not a success rate**, for the same reason `feat-004`'s
11 episodes are not: the tasks were chosen for site and eval-type coverage, `n`
is 10, and the population is `explicit`. It is a *cost* measurement, and that is
all `feat-006` should take from it.

---

## `feat-006` — the headline measurement, run 2026-07-31

**18 of 102 = 17.6%, against REAL's published ≤41% baseline. Deterministic
replicas are easier than live sites, so this is not comparable to a live-web
score.** Full accounting in `docs/DECISIONS.md` entry 16; run in `runs/full102/`.

`passed 18 / failed 26 / capped 56 / errored 2`, plus `10 excluded` (omnizon,
HTTP 451). `capped` is published apart from `failed` on purpose: **more than
half the population ran out of steps**, and calling that 82 failures would be a
different and less true sentence.

**Both subsets are published.** Judge-scored (`llm_boolean`, n=55): 8 passed,
14.5%. `jmespath`-scored (n=47): 10 passed, 21.3%. The n=47 shortcut entry 10
rejected would have published 21.3% — 3.7 points high — which is the empirical
answer to "is the cheap subset a fair sample". It is not.

**Cost, two columns, never summed.** Agent: 4 000 919 tokens over the 102 scored
attempts (4 097 114 over all 107, including the five that met a `429`), no dollar
figure because z.ai publishes no rate for this key. Judge: $0.007926 for 23
calls — the whole judged half of the headline cost under a cent.

### Three things this run learned that no earlier one could

**The 429 arrived, at seventeen minutes.** `429 / code 1302`, five attempts.
Entry 12's probes (12 concurrent accepted, 315 calls over 7 minutes clean) had
said explicitly that they could not rule out a quota later in a run, and that the
design answer was the non-terminal `provider_error`, not a bigger probe. It held:
no terminal record was written for any of the five, concurrency halved 3 → 1 and
recovered, round 2 re-ran exactly those five, and every task ended with **exactly
one terminal attempt**. One of the five went on to *pass* — a point of the
headline rate was resting on that rule.

**Entry 7's site rule was exercised for the first time and cost 9.7%.** The pilot
never reached it (one task per site). Over 102 tasks it reordered 52 launches
past 362 task-positions, which is free, and idled 1 121 worker-seconds of 11 618
— **all of it in the tail**, once the queue narrowed to two sites with thirteen
tasks left. If it is ever worth recovering, the fix is interleaving the
manifest's site order, not lifting the rule.

**The projection was right about tokens and wrong about wall clock.** 4.00 M
against a 3.51 M central estimate (inside the bounds); 76.3 min against 48.8.
The gap is the 429 recovery plus the site tail. The pilot's own warning — that
the cap rate was the dominant term and the least well measured — was correct: it
moved from 40% to 54.9%.

### What is new in the repo

`src/web_agent_eval/sites.py` probes every replica host from the URLs in the
installed task configs. `scripts/preflight.py` is now the only thing that writes
a manifest for a real run: it asserts the judge **with its control**, probes
reachability and freezes it into the manifest, records the **served** model
string beside the requested one, and re-reads the manifest to check population,
n, exclusion count and reason, concurrency and date before anything starts.
`scripts/run_batch.py` refuses a real run whose manifest has no reachability
record, so this is structural rather than remembered. A second probe after the
run (`postflight.json`) is what proves no host died mid-run — the before-probe
alone could not.

**55% of episodes ran out of steps at `lean` observation richness.** That is
`feat-007`'s subject, and entry 16 is what it will be measured against.
