# Session Handoff — web-agent-eval (P3)

## Current Objective

- **Goal:** Measure a web agent on REAL (112 tasks, 11 deterministic replica
  sites) with every number traceable to something that actually ran.
- **Current status:** `feat-001` `[GATE]` **passed**. One REAL task ran end to
  end on GLM and scored **1.0**. Nothing else is built. Next is `feat-002`.
- **Branch / commit:** `main`. No remote yet.

## Completed This Session

- [x] **`feat-001` [GATE].** `v1.gomail-2` on `glm-4.6` via z.ai:
      `cum_reward = 1.0`, 9 steps, 35.4 s wall clock, 20 931 GLM tokens.
      Reproduce with `uv run python scripts/run_gate.py`.
- [x] All three of the gate's questions answered with recorded command output —
      `docs/DECISIONS.md` entry 4.
- [x] Found and recorded two things the plan did not know: the z.ai key is a
      **Coding Plan** key on a different base URL, and one of the 11 sites has
      been **DMCA-taken-down** — entries 4 and 5.
- [x] `src/web_agent_eval/` created: `glm.py` (client) and `gate_agent.py`
      (minimal agent, gate scaffolding only). 5 new regression tests.

## The three answers, short form

| Question | Answer |
|---|---|
| 1. Custom OpenAI-compatible `base_url`? | **Yes — via `harness(agentargs=...)`.** NOT via `harness(model=...)`: the built-in agent routes on model-name prefix (`gpt-`/`claude-`/`openrouter/`/`local/`) and exposes no `base_url` at all. |
| 2. Sites local or hosted? | **Hosted, on Vercel** — `https://evals-<site>.vercel.app`, not `realevals.xyz` (that is the leaderboard). Nothing ships to serve them locally. Network latency stays; the migration bought determinism, not speed. |
| 3. Leaderboard key for local scoring? | **No.** `run_id` defaults to `'0'` and submission only fires when it is not `'0'`. **But** 60 of 112 tasks have an `llm_boolean` eval graded by an OpenAI `gpt-4.1` judge that agisdk hardcodes — a different key, and a `feat-005` problem. |

## Verification Evidence

| Check | Command | Result |
|---|---|---|
| Gate | `uv run python scripts/run_gate.py` | `cum_reward: 1.0`, `terminated: True`, `err_msg: None` |
| z.ai endpoint | direct HTTP probe | `paas/v4` → 429, `coding/paas/v4` → 200, bogus key → 401 |
| Sites | `curl` over all 11 hosts | 10 × 200, omnizon × 451 `DMCA_TAKEDOWN` |
| Lint | `uv run ruff check .` | `All checks passed!` |
| Tests | `uv run pytest -q` | `8 passed in 0.82s` |
| Full path | `./init.sh` | `=== All checks passed ===` |

## Decisions Made

Entries 4 and 5 appended to `docs/DECISIONS.md` this session; 1–3 predate it.

4. **The gate passed, and how.** The `agentargs` seam; the Coding Plan base URL
   (`https://api.z.ai/api/coding/paas/v4/`); `glm-4.6` reasons by default and
   needs `thinking: disabled`; local scoring needs no leaderboard key but
   `llm_boolean` tasks need an OpenAI one. Also records that the gate **failed
   twice before it passed**, and why.
5. **`evals-omnizon.vercel.app` is DMCA-taken-down.** 10 of 112 tasks are
   unrunnable. `feat-006`'s denominator is **n = 102** unless it returns.

## Blockers / Risks

- **`feat-006`'s denominator is 102, not 112**, and the exclusion count and
  reason must be published beside the rate.
- **`feat-005` has an unanswered cost question**: 60 of 112 tasks are graded by
  OpenAI `gpt-4.1`, not by z.ai. That is a second provider, a second key and a
  second cost line in a project whose subject is GLM. 47 tasks are both
  reachable and scorable with z.ai alone.
- **Replica sites are easier than live ones.** A score here is not comparable to
  a live-web score.

## Next Session Startup

1. Read `AGENTS.md`, then `feature_list.json`, then `docs/DECISIONS.md`.
2. Run `./init.sh` — expect all checks passed.
3. If the browser is missing: `uv run playwright install chromium` (agisdk pins
   Chromium build 1228; a mismatch fails with an error that does not look like a
   version problem).
4. Take `feat-002` and nothing else.

## Recommended Next Step

`feat-002`, the observation serializer. Two hard-won constraints carry into it,
both in DECISIONS entry 4: **the action must be extracted from the reply, never
passed through** (browsergym's parser turns prose into function calls), and
**`glm-4.6` needs `thinking: disabled`** or it spends the whole token budget on
reasoning it never returns.

`src/web_agent_eval/gate_agent.py` is scaffolding, not the project's agent — its
12 000-char axtree truncation is an arbitrary number and `feat-002` owes it
nothing.
