# Session Handoff — web-agent-eval (P3)

## Current Objective

- **Goal:** Measure a web agent on REAL (112 tasks, 11 deterministic replica
  sites) with every number traceable to something that actually ran.
- **Current status:** Scaffolded. **Zero features built, zero numbers measured.**
  Next is `feat-001`, the `[GATE]`.
- **Branch / commit:** `main`, initial scaffold commit. No remote yet.

## Completed This Session

- [x] Repo created and scaffolded with `harness-creator`, then rewritten for
      this project (the generated files are generic templates).
- [x] Python pinned to 3.12.12 via `uv`; `agisdk` 0.3.5 installed from PyPI.
- [x] `./init.sh` written for Python and **proven non-vacuous** — it failed the
      build on a real `ruff` error before passing.
- [x] `docs/DECISIONS.md` entries 1–3 written **before any feature exists**.
- [x] 8 features specified, all `not-started`.

## Verification Evidence

| Check | Command | Result |
|---|---|---|
| Environment | `uv run python -c "import agisdk…"` | `python: 3.12.12`, `REAL.harness callable` |
| Lint | `uv run ruff check .` | `All checks passed!` |
| Tests | `uv run pytest -q` | `3 passed in 0.80s` |
| Full path | `./init.sh` | `=== All checks passed ===` |
| Secret safety | `git check-ignore -v .env` | `.gitignore:2:.env` |
| Harness score | `validate-harness.mjs` | see root `progress.md` |

## Decisions Made

All in `docs/DECISIONS.md`, written before any dependent code:

1. **Benchmark is REAL**, and **"unseen real sites" is no longer claimed.** The
   reason is wall-clock (an eight-hour run that produced nothing; a nine-minute
   hang inside one action) and, more importantly, that deterministic pages make
   the `feat-007` ablation valid instead of confounded.
2. **Python pinned to 3.12**; `agisdk` from **PyPI 0.3.5**, not a clone — the
   PyPI release is newer than the repo's `main`.
3. **Licensing is two licenses:** `agisdk` is MIT, the replicas are
   non-commercial research use. Never conflate them.

## Blockers / Risks

- **`feat-001` is a `[GATE]` and may fail.** If GLM cannot drive `agisdk`, stop
  and report. Do **not** switch to a paid OpenAI or Anthropic model — that
  changes both the cost profile and the subject of the project.
- **Nothing about GLM is established from this repo.** Custom `base_url` support
  is inferred from the `openai>=1.0.0` dependency. Inference is not evidence.
- **Local vs hosted replica sites is undetermined.**
- **Replica sites are easier than live ones.** A score here is not comparable to
  a live-web score.

## Next Session Startup

1. Read `AGENTS.md`, then `feature_list.json`, then `docs/DECISIONS.md`.
2. Run `./init.sh` — expect all checks passed.
3. Take `feat-001` and nothing else.

## Recommended Next Step

`feat-001`. It answers all three open questions at once and everything else
depends on it. Its questions are written out in `docs/DECISIONS.md` entry 3 so
they survive into whichever session runs it.
