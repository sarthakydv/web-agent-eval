# Progress — web-agent-eval (P3)

## Current State

**Last Updated:** 2026-07-31
**Active Feature:** none — `feat-001` … `feat-004` are done, next is `feat-005`
**Status:** the `[GATE]` is through (one REAL task scored **1.0**), the
observation serializer exists with richness as a parameter and a measured token
budget, the **episode loop is built and bounded**, and the **batch runner and
supervisor are built, tested and proven against a real SIGKILL, a real 429 and a
real budget overrun**. `feat-005` is **blocked on a human step**: the
`OPENAI_API_KEY` placeholder in `.env` must be filled (entry 10). The repo is
**public** at `github.com/sarthakydv/web-agent-eval` with CI green.

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

### What's In Progress

- Nothing. Stopped after `feat-004` as instructed, before `feat-005`.

### What's Next

1. **`feat-005` needs a human step first: fill `OPENAI_API_KEY` in `.env`.**
   It is a placeholder today. 60 of the 112 tasks have an `llm_boolean` eval
   that agisdk grades with a hardcoded OpenAI `gpt-4.1` judge (entries 4 and
   10), so without it the population is 47 rather than 102 and the denominator
   stops being comparable to REAL's published baseline.
2. `feat-006` chooses the population — 112, 102 or 47 — and the runner already
   freezes that choice into `runs/<run-id>/manifest.json` with every exclusion
   and its reason. `--population 47` runs today with no OpenAI key at all.
3. The full run is `uv run python scripts/supervise.py --run-id <id>
   --population <112|102|47>`; it resumes on its own after any interruption and
   is a no-op once complete.

## Blockers / Risks

- [ ] **10 of the 112 tasks cannot run.** `evals-omnizon.vercel.app` returns
      HTTP 451 `DMCA_TAKEDOWN`. `feat-006`'s denominator is **n = 102** unless
      the site returns, and the count and reason must be published beside the
      rate — DECISIONS entry 5.
- [ ] **60 of the 112 tasks are graded by an OpenAI judge, not by z.ai.**
      `WebCloneEvaluator` hardcodes `gpt-4.1` for `llm_boolean` evals. This is a
      cost and comparability question `feat-005` must answer. 47 tasks are both
      reachable and scorable with no key but z.ai's.
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

## Files Modified This Session

`feat-004`, the batch runner and supervisor: `src/web_agent_eval/{manifest,
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
- [x] Tests pass: `uv run pytest -q` → `126 passed in 117.98s`
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
second kind.
