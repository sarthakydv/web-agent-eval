# Progress — web-agent-eval (P3)

## Current State

**Last Updated:** 2026-07-31
**Active Feature:** none — `feat-001` and `feat-002` are done, next is `feat-003`
**Status:** the `[GATE]` is through (one REAL task scored **1.0**) and the
observation serializer exists, with richness as a parameter and a measured token
budget. The agent loop and its caps are not built. The repo is now **public** at
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
- [x] 46 tests passing; the 38 serializer/token tests run with no browser and
      no API key.
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

- Nothing. Stopped after `feat-002` as instructed. `feat-003` is not started.

### What's Next

1. `feat-003` — the agent loop with caps on steps, tokens and wall-clock. Only a
   wall-clock race bounds an action; per-operation timeouts do not.
2. Two things `feat-003` inherits from the gate and must not
   rediscover — both are in DECISIONS entry 4:
   - **Extract the action; never hand browsergym the raw reply.** Its parser
     scans the whole string and pyparsing skips whitespace, so prose like
     `"the checkbox is already checked (checked='true')"` parses as a call and
     kills the step. Regression tests are in `tests/test_gate_agent.py`.
   - **`glm-4.6` reasons by default** and will burn the whole `max_tokens`
     budget on thinking it never returns. Send
     `extra_body={"thinking": {"type": "disabled"}}`.

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

## Files Modified This Session

Harness validation and first public push — **no feature work**, and `src/` and
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
- [x] Tests pass: `uv run pytest -q` → `46 passed in 2.15s`
- [x] Lint clean: `uv run ruff check .` → `All checks passed!`
- [x] Full path: `./init.sh` → `=== All checks passed ===`

## Notes for Next Session

**One cleanup is outstanding.** The pre-rewrite refs are still local:
`refs/original/refs/heads/main` and the `backup-pre-rewrite` branch, both at the
old `e630a16`. They are not reachable from `main` and were not pushed, but a
future `git push --all` or `--mirror` would publish them. Delete both and `gc`
once the rewrite is trusted.

Setup gained one step: **`uv run playwright install chromium`**. `agisdk` pins
Chromium build 1228 and a mismatched build fails the run with an error that
looks nothing like a version problem.

`src/web_agent_eval/gate_agent.py` is still gate scaffolding, not the project's
agent. `feat-003` owns the loop and its caps and owes it nothing — its
12 000-char axtree truncation in particular was an arbitrary number, and the
measured budget that replaces it lives in `observation.py`.

`feat-003` should call `serialize(obs, level)` and must **not** run agisdk's
`default_obs_preprocessor`, which deletes `axtree_object` and `dom_object`. The
serializer falls back to a pre-flattened tree and says so in the text, but a
fallback is not the richness level anyone asked for.

Two accounting lines exist now and must never be mixed: **budget accounting** is
local `tiktoken` over a rendered observation; **cost accounting** (`feat-005`) is
the provider's `usage` field summed from real responses. Entry 4's 20 931 is the
second kind.
