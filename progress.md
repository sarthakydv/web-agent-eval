# Progress — web-agent-eval (P3)

## Current State

**Last Updated:** 2026-07-31
**Active Feature:** none — next is `feat-001`, the `[GATE]`
**Status:** scaffolded. Zero features built, zero numbers measured.

## Status

### What's Done

- [x] Python pinned to **3.12.12** via `uv`; `agisdk` **0.3.5** from PyPI
      installs and imports; `REAL.harness` is callable.
- [x] `./init.sh` runs environment checks, `ruff` and `pytest`, and fails loudly.
      **Proven non-vacuous:** on its first run it caught a real `ruff` error
      (`PLW1510`, `subprocess.run` without `check`) and failed the build until
      it was fixed.
- [x] 3 environment tests passing, including one asserting `.env` is never
      tracked by git.
- [x] `docs/DECISIONS.md` entries 1–3 written **before any feature exists**.

### What's In Progress

- Nothing. The repo is clean and ready for a runner.

### What's Next

1. `feat-001` — the `[GATE]`. One REAL task end to end on GLM.
2. Nothing else until that gate reports.

## Blockers / Risks

- [ ] **`feat-001` may fail.** If GLM cannot drive `agisdk`, that is a scoping
      conversation about model and cost — **not** a licence to switch to a paid
      OpenAI or Anthropic model. GLM is the subject of this project.
- [ ] **Nothing about GLM is established.** No model call has been made from
      this repo. That `agisdk` accepts a custom `base_url` is *inferred* from its
      `openai>=1.0.0` dependency. Inference is not evidence.
- [ ] **Local vs hosted sites is undetermined** — it decides how much of the
      speed gain from leaving the live web is actually real.
- [ ] **Replica sites are easier than live sites.** A score here is not
      comparable to a live-web score and must never be presented as one.

## Decisions Made

- **Benchmark is REAL; "unseen real sites" is no longer claimed.**
  Context and full reasoning in `docs/DECISIONS.md` entry 1. This is the
  project's second benchmark change, superseded rather than rewritten.
- **Python pinned to 3.12**, though `agisdk` allows ≥3.9 — entry 2.
- **`agisdk` from PyPI (0.3.5)**, not a clone as its README says; the PyPI
  release is newer than the repo's `main` — entry 2.

## Files Modified This Session

Scaffolding only — no feature code:
`AGENTS.md`, `feature_list.json`, `init.sh`, `progress.md`, `session-handoff.md`,
`README.md`, `pyproject.toml`, `.gitignore`, `docs/DECISIONS.md`,
`tests/test_environment.py`.

## Evidence of Completion

- [x] Tests pass: `uv run pytest -q` → `3 passed in 0.80s`
- [x] Lint clean: `uv run ruff check .` → `All checks passed!`
- [x] Environment: `python: 3.12.12`, `agisdk: import ok, REAL.harness callable`
- [x] Secret safety: `git check-ignore -v .env` → `.gitignore:2:.env`

## Notes for Next Session

Take `feat-001` and nothing else. It is a `[GATE]`: if GLM cannot be wired up,
stop and report rather than substituting a paid model. Its three questions are
written out in `docs/DECISIONS.md` entry 3 so they survive into the session that
runs it.
