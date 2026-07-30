# Progress — web-agent-eval (P3)

## Current State

**Last Updated:** 2026-07-31
**Active Feature:** none — `feat-001` is done, next is `feat-002`
**Status:** the `[GATE]` is through. GLM drives agisdk and one REAL task scored
**1.0**. Nothing else has been built.

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

### What's In Progress

- Nothing. Stopped at the gate as instructed. `feat-002` is not started.

### What's Next

1. `feat-002` — observation serializer, with richness as a parameter.
2. Two things `feat-002`/`feat-003` inherit from the gate and must not
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

## Files Modified This Session

`src/web_agent_eval/{__init__,glm,gate_agent}.py`, `scripts/run_gate.py`,
`tests/test_gate_agent.py`, `pyproject.toml`, `feature_list.json`,
`docs/DECISIONS.md`, `progress.md`, `session-handoff.md`.

## Evidence of Completion

- [x] Gate run: `cum_reward: 1.0`, `terminated: True`, `err_msg: None` on
      `v1.gomail-2`; full transcript in `feature_list.json`'s evidence field.
- [x] Tests pass: `uv run pytest -q` → `8 passed in 0.82s`
- [x] Lint clean: `uv run ruff check .` → `All checks passed!`
- [x] Full path: `./init.sh` → `=== All checks passed ===`

## Notes for Next Session

Setup gained one step: **`uv run playwright install chromium`**. `agisdk` pins
Chromium build 1228 and a mismatched build fails the run with an error that
looks nothing like a version problem.

`src/web_agent_eval/gate_agent.py` is gate scaffolding, not the project's agent.
`feat-002` owns the observation serializer and `feat-003` owns the loop and its
caps; nothing in `GateAgent` is a design decision for either. Its 12 000-char
axtree truncation in particular is an arbitrary number, not a measured budget.
