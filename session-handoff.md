# Session Handoff — web-agent-eval (P3)

## Current Objective

- **Goal:** Measure a web agent on REAL (112 tasks, 11 deterministic replica
  sites) with every number traceable to something that actually ran.
- **Current status:** `feat-001` `[GATE]` **passed** and `feat-002` **done**. One
  REAL task ran end to end on GLM and scored **1.0**; the observation serializer
  now renders that kind of observation at a parameterised richness level under a
  measured token budget. The agent loop is not built. Next is `feat-003`.
- **Branch / commit:** `main`, tracking `origin/main` at
  `github.com/sarthakydv/web-agent-eval` (**public**). CI green.

## Completed This Session (harness validation and first public push)

No feature work. `feat-003` was not started and `src/` and `scripts/` were not
touched.

- [x] **The three tracker rules are enforced and each was proven to bite.**
      `init.sh` fails on a missing `verification` command, a `done` feature with
      empty `evidence`, and two features `in-progress`. Each was broken in a
      scratch copy, confirmed to exit **1** with a message naming the problem,
      then restored and checksum-verified. `ci.yml` holds a second copy of the
      same logic, extracted verbatim and tested against the same three files.
- [x] **`.github/workflows/ci.yml`** — the offline half of `init.sh`, all six
      steps run locally as written before pushing, and green on the first CI run.
- [x] **Pre-push audit of a repo that had never been public.** No key and no
      `.env`/`.dev.vars`/credential blob anywhere in history, including inside the
      gzipped and PNG fixtures once decompressed; no `Co-Authored-By` and no agent
      named on any commit; all four commits authored by Sarthak.
- [x] **History rewritten once before the first push** to drop one out-of-scope
      line from the root commit's `progress.md`. The commit whose only content was
      removing that line became empty and was pruned, leaving 4 commits. The
      published tree is byte-identical to the pre-rewrite tree (both
      `cc8e3e5351e37ea52b1a30de103ef3118befdcaf`).
- [x] **`docs/DECISIONS.md` entries 7 and 8** — the run loop `feat-004` must
      implement, and the harness change with its broken-gate output.

## Previous Session (`feat-002`)

- [x] **`src/web_agent_eval/observation.py`** — one direction, observation to
      text. `Richness` is a frozen dataclass and `serialize(obs, level)` takes
      one, so `feat-007` varies a data object rather than a branch. A
      caller-defined level needs no change to `serialize()`, and a test asserts
      that.
- [x] **Two levels ship.** `lean` = visible nodes carrying a bid, no
      annotations, no HTML. `rich` = every visible node with visibility,
      clickability and centre coordinates, plus pruned HTML, open tabs, focused
      element and a screenshot note. On a loaded page `rich` costs 4x-6x `lean`.
- [x] **Fixtures are real captures, and the gate had left none.** Its four run
      directories hold `summary_info.json`, `experiment.log`, `exp_args.pkl`,
      `goal_object.pkl.gz` and `finish_state.json` — no DOM, no accessibility
      tree, no screenshot. Five observations were captured fresh from live runs
      on two sites (`scripts/capture_observations.py`) and committed under
      `fixtures/observations/`.
- [x] **Token budget stated and measured**, in both units — see the table below.
- [x] **38 new tests**, none of which start a browser or need an API key.

## The budget, in the two units it exists in

| | |
|---|---|
| Claim | **no rendered observation exceeds 12 000 tokens as z.ai counts them** |
| Enforced locally at | **11 741** `cl100k_base` tokens (12 000 / 1.022) |
| Why the margin | `cl100k_base` understates z.ai's `prompt_tokens` by up to **2.2%**, measured on 10 real calls |
| Largest provider count observed | **11 979** ≤ 12 000 |
| Rejected alternative | `o200k_base` — overstates by 2.2% aggregate and swings 0.943–1.025 per case |

**Method:** two real chat completions per fixture/level, byte-identical apart
from the observation text, differenced on `prompt_tokens`. Identical framing on
both sides, so the difference is z.ai's count of exactly what the serializer
produced. `uv run python scripts/token_check.py` reproduces it.

**This is not entry 4's 20 931.** That was `usage` summed over a whole 9-step
episode — prompts and completions — not a local count of one observation. Budget
accounting (local, offline, testable) and cost accounting (`feat-005`, provider
`usage` only) stay separate from here on.

## Verification Evidence

| Check | Command | Result |
|---|---|---|
| Two levels, one budget | `uv run python scripts/render_observation.py` | 10 rows, all `ok=True`; `lean` 88–2 309, `rich` 550–11 738 tokens |
| Local vs provider count | `uv run python scripts/token_check.py` | `glm/cl100k` = 1.015 aggregate, 1.022 worst case |
| No browser, no key | `env -u ZAI_API_KEY uv run pytest tests/test_observation.py tests/test_tokens.py -q` | `38 passed in 2.26s` |
| Lint | `uv run ruff check .` | `All checks passed!` |
| Full path | `./init.sh` | `46 passed`, `=== All checks passed ===` |

## Decisions Made

Entries 7 and 8 appended this session; 1–6 predate it.

7. **The run loop** — a manifest frozen before the first task that names its own
   population, provider errors recorded as non-terminal and never scored as task
   failures, attempts that append with the rate read from each task's first
   terminal attempt, and a supervisor with three machine-checkable exits (0 all
   terminal, 1 stalled, 2 budget exceeded). Decided before `feat-004` exists
   because none of it can be applied honestly after seeing results.
8. **The tracker enforces its own rules**, with the broken-gate output recorded;
   CI runs the offline half of `init.sh`; and two ways a scan reported "clean"
   while it was not — `grep` here is ugrep and honours `.gitignore`, and
   `git grep -E` has no `\b` word boundary. Both were caught only by running a
   positive control before trusting a negative.

Entry 6 covers the serializer and token accounting; 1–5 predate it.

6. **The serializer, its richness seam and the token accounting.** Why the
   fixtures had to be captured rather than reused; what the two levels differ in
   and what they deliberately do not (goal, URL and last-action error render at
   every level, because dropping them changes the task rather than the richness);
   the screenshot contributes its dimensions and nothing else, because `glm-4.6`
   via z.ai is text-only; and the measured disagreement between the local
   tokenizer and the provider's own count.

## Blockers / Risks

- **`feat-006`'s denominator is 102, not 112.** `evals-omnizon.vercel.app` is
  DMCA-taken-down (451). The count and reason must be published beside any rate.
  Nothing in `feat-002` works around it — entry 5, and it is a human decision.
- **`feat-005` has an unanswered cost question**: 60 of 112 tasks are graded by
  an OpenAI `gpt-4.1` judge, not by z.ai. 47 tasks are both reachable and
  scorable with z.ai alone.
- **`rich` truncates on large pages.** On both staynb fixtures the budget binds
  and lines are dropped (reported per section, never silently). That is a real
  property of the arm `feat-007` will compare, not a bug to hide.
- **Replica sites are easier than live ones.** A score here is not comparable to
  a live-web score.

## Next Session Startup

1. Read `AGENTS.md`, then `feature_list.json`, then `docs/DECISIONS.md` —
   **entry 7 before writing any of `feat-004`**.
2. Run `./init.sh` — expect `46 passed` and all checks passed.
3. If the browser is missing: `uv run playwright install chromium` (agisdk pins
   Chromium build 1228; a mismatch fails with an error that does not look like a
   version problem).
4. Take `feat-003` and nothing else.

Nothing is outstanding. `main` is the only local branch, the pre-rewrite refs have
been deleted and garbage-collected, and `main == origin/main`.

## Recommended Next Step

`feat-003`, the agent loop with caps. Four things carry into it:

- **Only a wall-clock race bounds an action.** Per-operation timeouts do not —
  the predecessor sat on one site for nine minutes with every sub-timeout at
  45 s or less.
- **Extract the action; never hand browsergym the raw reply** — its parser turns
  English prose into function calls. `extract_action` and its regression tests
  already exist and stay on the action side.
- **`glm-4.6` needs `extra_body={"thinking": {"type": "disabled"}}`** or it
  spends the whole `max_tokens` budget on reasoning it never returns.
- **Call `serialize(obs, level)` and do not run agisdk's
  `default_obs_preprocessor`** — it deletes `axtree_object` and `dom_object`.
  The serializer falls back to a pre-flattened tree and labels it in the text,
  but a fallback is not the richness level the ablation asked for.

`src/web_agent_eval/gate_agent.py` is still gate scaffolding. Its 12 000-*char*
axtree truncation was an arbitrary number; the measured budget that replaces it
lives in `observation.py`.
