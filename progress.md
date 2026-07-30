# Progress — web-agent-eval (P3)

## Current State

**Last Updated:** 2026-07-31
**Active Feature:** none — `feat-001`, `feat-002` and `feat-003` are done, next
is `feat-004`
**Status:** the `[GATE]` is through (one REAL task scored **1.0**), the
observation serializer exists with richness as a parameter and a measured token
budget, and the **episode loop is built and bounded** — steps, tokens and wall
clock, each firing on its own and each recorded when it does. The batch runner
and supervisor are not built. The repo is **public** at
`github.com/sarthakydv/web-agent-eval` with CI green.

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
- [x] 76 tests passing; all of them run with no browser, no network and no
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

- Nothing. Stopped after `feat-003` as instructed. `feat-004` is not started.

### What's Next

1. `feat-004` — the batch runner and supervisor over the 112 (102 reachable),
   with resume. **Its rules are already decided in DECISIONS entry 7 and must
   not be re-litigated mid-run:** frozen manifest, provider errors that are not
   task failures, attempts that append and score the first terminal attempt, and
   a supervisor that stops on a machine-checkable condition.
2. `feat-004` consumes `run_episode()` and must map its three outcomes onto
   entry 7's four terminal statuses: `completed` + reward → `passed`/`failed`,
   `capped` counted and published **separately**, `errored` as-is. The cap
   reason is already machine-readable: `{"cap": "wall_clock", "limit": 300.0,
   "observed": 300.4, "unit": "seconds"}`.
3. **Workers are processes, not threads** (entry 7): Playwright's sync API has
   thread affinity, and a process boundary is what reclaims a browser left
   wedged by a wall-clock cap. The loop reports `cleanup.wedged_on` when that
   happens rather than claiming a clean close.
4. **Probe the real concurrency limit before the full run.** Entry 7's 3 is
   z.ai's *published* pay-as-you-go number and this is a Coding Plan key.

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

## Files Modified This Session

`feat-003`, the episode loop: `src/web_agent_eval/{episode,caps,policy,
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
- [x] Tests pass: `uv run pytest -q` → `76 passed in 2.96s`
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

`AgisdkEnvironment` is the one piece **no test exercises** — it needs a browser
and the hosted sites. `feat-004`'s first run is its first real exercise, and it
should be run on one task before a batch.

Two accounting lines exist now and must never be mixed: **budget accounting** is
local `tiktoken` over a rendered observation; **cost accounting** (`feat-005`) is
the provider's `usage` field summed from real responses. Entry 4's 20 931 is the
second kind.
