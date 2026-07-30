# Session Handoff — web-agent-eval (P3)

## Current Objective

- **Goal:** Measure a web agent on REAL (112 tasks, 11 deterministic replica
  sites) with every number traceable to something that actually ran.
- **Current status:** `feat-001` `[GATE]` **passed**, `feat-002` **done**,
  `feat-003` **done**. One REAL task ran end to end on GLM and scored **1.0**;
  the observation serializer renders that kind of observation at a parameterised
  richness level under a measured token budget; and the episode loop now runs
  observe → decide → act → terminate under three independent caps, each of which
  ends the episode cleanly and says which one fired. The batch runner is not
  built. Next is `feat-004`.
- **Branch / commit:** `main`, tracking `origin/main` at
  `github.com/sarthakydv/web-agent-eval` (**public**). CI green.

## Completed This Session (`feat-003` — the episode loop with caps)

- [x] **`src/web_agent_eval/episode.py`** — `run_episode()`: reset, then observe
      → decide → act until the environment terminates or a cap fires. It takes
      an `env_factory` and a `policy_factory` and calls them **inside** the
      episode, returns one `EpisodeRecord`, and **never raises**.
- [x] **`src/web_agent_eval/caps.py`** — `Caps`, `Deadline`, `TokenLedger`,
      `BoundedRunner`, `CapHit`. One set per episode; nothing module-level and
      mutable, nothing cached across episodes.
- [x] **`src/web_agent_eval/policy.py`** — `GlmPolicy`, the decide half. Takes a
      `Richness` (does not pick one), sends `thinking: disabled` and
      `max_tokens=1024` on every call, and extracts one action from the reply.
- [x] **`src/web_agent_eval/environment.py`** — `AgisdkEnvironment`, a thin
      adapter over the raw gym env `agisdk` builds. **Exercised by no test** —
      see Blockers.
- [x] **`src/web_agent_eval/action.py`** — `extract_action` moved out of
      `gate_agent.py`. Entry 6 says it lives on the action side; it is not gate
      scaffolding, and `tests/test_gate_agent.py` covers it unchanged.
- [x] **`scripts/cap_budget.py`** — derives the token cap offline, and exits
      non-zero if the chosen cap could bite on an honest episode.
- [x] **30 new tests**, none of which start a browser, make a network call or
      need an API key.

## The wall-clock cap bounds the step, not the gap between steps

The inherited lesson, and the reason the loop has the shape it does. **Two ways
to get it wrong were available and both are closed:**

1. Per-operation timeouts do not compose into a bound on the operation — the
   predecessor sat on one site for nine minutes with every sub-timeout at 45 s
   or less.
2. **A cap checked between steps is not a wall-clock cap.** One hanging step
   sails straight past it, because the check never runs.

So the episode owns a `Deadline`, and every operation — building the policy,
building the environment, `reset`, `propose`, `step` — is submitted to that
episode's **own single worker thread** and awaited with
`future.result(timeout=deadline.remaining())`. One thread, not a pool: agisdk
drives Playwright's *sync* API, which has thread affinity. The policy's own
request timeout is **derived from** the same deadline rather than set
independently of it.

Python cannot kill the thread it leaves behind. The runner refuses to submit
anything more once an operation outruns its bound, and the record says
`cleanup: {"wedged_on": "env.step", "env_closed": false}` rather than claiming a
clean close. **Entry 7's "workers are processes" is now load-bearing** — process
exit is what reclaims a wedged browser.

## The cap values, and where each came from

| Cap | Value | Kind | Basis |
|---|---|---|---|
| `max_steps` | **25** | decision | agisdk's harness default; the gate's successful episode took 9 (entry 4) |
| `max_tokens` | **400 000** | **derived** | `scripts/cap_budget.py` — worst honest episode 354 350 provider tokens, **1.13x** headroom |
| `max_wall_clock_s` | **300** | decision | gate episode 35.4 s / 9 calls; site round trips 0.13–2.37 s; ~3x expected worst case |

The token cap had to be derived rather than chosen: entry 9 measured reasoning
spend **scaling with the token cap**, which makes it an input to claim 2 (tokens
per task), not only a safety bound. The requirement is that it **never bites on
an honest episode** — a cap that fired on the rich arm and not the lean one would
truncate one side of `feat-007`'s ablation. **It is held constant across every
arm**, along with `max_tokens=1024` and `thinking: disabled`.

**The cap is enforced on z.ai's own `usage`.** Every completion returns one
(entry 4). Only when a response arrives without `usage` is the cost
reconstructed locally and marked up by entry 6's measured **1.022** worst-case
undercount, so the fallback errs toward charging more than the provider would.
The record reports `provider_tokens`, `local_tokens` and `charged` separately.

## Verification Evidence

| Check | Command | Result |
|---|---|---|
| **`feat-003` verification** | `uv run pytest -q -k caps` | `25 passed, 51 deselected in 1.31s` |
| Cap derivation | `uv run python scripts/cap_budget.py` | worst honest episode `354,350`; cap `400,000`; headroom `1.13x`; `OK` |
| No browser, no key | `env -u ZAI_API_KEY uv run pytest -q` | `76 passed in 2.91s` |
| Lint | `uv run ruff check .` | `All checks passed!` |
| Full path | `./init.sh` | `76 passed`, `=== All checks passed ===` |

Each cap fires in isolation, each has a **control asserting it does not fire**
when it should not, and the wall-clock case asserts on **elapsed time** — a test
that only read the returned reason would pass even if the loop hung for nine
minutes first.

### Four deliberate breaks, to prove the suite is not vacuous

| Break | Result |
|---|---|
| `future.result()` with no timeout | `test_..._bound_the_step_itself` fails: **"the loop took 20.1s to give up"** |
| charge the raw local count, no margin | fails: `assert 10000 == (1022 * 10)` |
| let `WallClockExceeded` escape the loop | 2 wall-clock tests fail; the cap is recorded as `errored` |
| step cap `>` instead of `>=` | 3 tests fail: "steps cap: 3 steps against a limit of 2" |

## Decisions Made

Entry 11 was appended this session; 1–10 predate it.

11. **The episode loop and its three caps.** Why the deadline bounds the step
    itself and what that costs (a thread Python cannot kill, reported rather
    than hidden); the token cap enforced on the provider's numbers with the
    measured margin on the fallback only; the derivation of 400 000 and why it
    is set clear of the worst case rather than tight to it; the three outcomes
    and the rule that one is always recorded; the fixed precedence when two caps
    cross at once; and the concurrency-safety properties `feat-004` depends on.

Entry 7 is the one to read **before writing any of `feat-004`**: frozen
manifest, provider errors that are not task failures, attempts that append with
the rate read from each task's first terminal attempt, and a supervisor with
three machine-checkable exits.

## Blockers / Risks

- **`AgisdkEnvironment` is exercised by no test.** It needs a browser and the
  hosted sites, and `feat-003`'s tests run against fakes on purpose — the caps
  are the subject, and a browser would make the wall-clock case slow and flaky.
  **`feat-004` should run one real task through `run_episode` before a batch.**
  This is stated in entry 11 rather than left implied by its presence.
- **`feat-006`'s denominator is 102, not 112.** `evals-omnizon.vercel.app` is
  DMCA-taken-down (451). The count and reason must be published beside any rate.
- **`feat-005` has an unanswered cost question**: 60 of 112 tasks are graded by
  an OpenAI `gpt-4.1` judge (entry 10), not by z.ai. 47 are both reachable and
  scorable with z.ai alone.
- **Entry 7's concurrency limit of 3 is z.ai's *published* pay-as-you-go
  number** and this is a Coding Plan key. Probe it before the full run; a
  concurrency rejection is a `provider_error`, never a task failure.
- **`rich` truncates on large pages** (reported per section, never silently).
  A real property of the arm `feat-007` compares, not a bug.
- **Replica sites are easier than live ones.** A score here is not comparable to
  a live-web score.

## Next Session Startup

1. Read `AGENTS.md`, then **only `feat-004`'s entry** in `feature_list.json`,
   then the index at the top of `docs/DECISIONS.md` — **entry 7 before writing
   any of `feat-004`**, plus entry 11 for the loop it wraps. Neither file is
   read end to end.
2. Run `./init.sh` — expect `76 passed` and all checks passed.
3. If the browser is missing: `uv run playwright install chromium` (agisdk pins
   Chromium build 1228; a mismatch fails with an error that does not look like a
   version problem).
4. Take `feat-004` and nothing else.

Nothing is outstanding. `main` is the only local branch and `main == origin/main`.

## Recommended Next Step

`feat-004`, the batch runner and supervisor. Four things carry into it:

- **Entry 7's rules were decided before it existed and are not to be
  re-litigated mid-run.** Frozen manifest, `provider_error` as non-terminal,
  attempts append and the score reads the **first** terminal attempt, supervisor
  stops on a condition.
- **Map the loop's three outcomes onto entry 7's four statuses.** `completed` +
  reward → `passed`/`failed`; `capped` is **counted and published separately**;
  `errored` as-is. The cap reason is already machine-readable:
  `{"cap": "wall_clock", "limit": 300.0, "observed": 300.4, "unit": "seconds"}`.
- **Workers are processes, not threads.** Playwright thread affinity, and
  process exit is what reclaims a browser left wedged by a wall-clock cap.
- **`run_episode` writes only where the caller says.** Give each episode its own
  path under `runs/<run-id>/` so three concurrent workers cannot collide.
