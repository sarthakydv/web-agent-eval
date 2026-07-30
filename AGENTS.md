# AGENTS.md — web-agent-eval (P3)

A web agent measured on **REAL**: 112 tasks across 11 deterministic replica
sites. The point of this repo is that every number in it is measured, and that
the score is comparable to a published baseline.

## Startup Workflow

1. `pwd` — confirm you are in `web-agent-eval`.
2. Read this file, then `feature_list.json`, then `docs/DECISIONS.md`.
3. Run `./init.sh`. If it fails, fix that before adding scope.
4. `git log --oneline -5`.

## Working Rules

- **One feature at a time.** Take the id you were given and nothing else.
- **`uv run` everything.** Python is pinned to 3.12; the system interpreter is
  3.14 and is not supported by this project's dependency set.
- **Never invent a number.** Every figure in `README.md` or `docs/DECISIONS.md`
  comes from something that actually ran. If it is unmeasured it is `TBD`.
- **Stop rather than substitute.** A `[GATE]` feature marks a place where an easy
  workaround exists that would keep the demo alive while making a claim false.
  Stop and report; do not work around it.
- **Evidence is output, not assertion.** Paste real command output into the
  `evidence` field. "Tests pass" is not evidence; the test output is.
- **No `Co-Authored-By` trailer**, ever.
- Stay in scope. Do not touch files unrelated to your feature.

## Feature list rules

`feature_list.json` is the only source of scope. Each feature carries `id`,
`name`, `description`, `dependencies`, `verification`, `status`, `evidence`.
There is no `docs/TASKS.md` here — a feature's detail is its `description`, and
its acceptance check is its `verification`.

- **`verification` is the command that decides done**, written before the work
  starts. If it cannot be run, it is not a verification.
- `status` moves to `done` only after that command has actually run and its
  **output** is in `evidence`.
- **One feature `in-progress` at a time.** `./init.sh` fails on two.
- `./init.sh` also fails on a `done` feature with an empty evidence field, and
  on any feature missing its verification command.

## What this project measures

Two things, and nothing beyond them:

1. A success rate on REAL's 112 tasks, stated against the published **≤41%**
   baseline, with the method described.
2. **Tokens per task**, under explicit step, token and wall-clock caps, with
   resumable batch execution. A dollar figure only if z.ai publishes rates — if
   it does not, say so rather than estimating.

**A claim this project does NOT make:** "unseen real sites". That died with the
move off the live web. REAL's sites are deterministic replicas, and the honest
framing is reproducibility, not novelty. See `docs/DECISIONS.md` entry 1.

## Two lessons inherited from the archived predecessor

These cost real time once. Do not rediscover them.

1. **Per-operation timeouts are not a bound on the whole operation.** A run once
   sat on a single site for nine minutes with every sub-timeout set to 45 s or
   less. Only a wall-clock race bounds an action.
2. **A long run must checkpoint and resume.** An eight-hour run once produced
   nothing because it could not be resumed after a failure.

The run loop that follows from this is specified in **`docs/DECISIONS.md` entry
7** — frozen manifest, provider errors that are not task failures, attempts that
append, and a supervisor that stops on a condition rather than a judgement.
Those rules were decided before `feat-004` existed, because none of them can be
applied honestly after seeing the results. Implement them; do not re-litigate
them mid-run.

## Definition of Done

1. The behaviour works.
2. Verification actually ran, and its **output** is in `feature_list.json`'s
   `evidence` field.
3. Any decision or measurement is appended to `docs/DECISIONS.md`.
4. `./init.sh` passes and the repo is committed.

## End of Session

Before ending a session, in this order:

1. Paste the real verification output into the feature's `evidence` field.
2. Append any decision or measurement to `docs/DECISIONS.md`.
3. Update `progress.md` and `session-handoff.md`, and say which feature is
   mid-flight if one is.
4. Commit. Leave the working tree **clean** and the repo **restartable** — the
   next session must be able to run `./init.sh` immediately and have it pass.

A long run is the one exception worth planning for: `feat-004` onward must
checkpoint, so an interrupted batch resumes rather than restarting.

## Escalation

- `[GATE]` fails → stop, record the exact error, report. Do not substitute.
- A measurement comes out worse than hoped → use the real number. That is the
  entire point of this project.
- Scope drifting toward "a product" → re-read the two claims above.

## Verification

```bash
./init.sh          # secrets check, lint, typecheck-equivalent, tests
```
