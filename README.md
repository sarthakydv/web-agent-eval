# web-agent-eval

A web agent measured on [REAL](https://github.com/agi-inc/REAL) — 112 tasks
across 11 deterministic replica sites.

> **Status: measured, 2026-07-31.** No figure appears in this README that does
> not trace to an entry in [`docs/DECISIONS.md`](docs/DECISIONS.md). Anything not
> yet produced by something that ran stays `TBD`.

## What this measures

| | |
|---|---|
| Success rate, **n = 102** | **17.6%** (18/102) — against a published **≤41%** baseline |
| Tokens per task | **39,225 mean** (4,000,919 agent tokens over 102 tasks) |

**Deterministic replicas are easier than live sites, so 17.6% is not comparable
to a live-web score.** That qualifier goes with the number wherever it appears.

`n = 102`, not 112: the omnizon replica returns HTTP 451 (`DMCA_TAKEDOWN`), so
its 10 tasks cannot run. The count and the reason are published beside the rate,
never a denominator left unstated. Of the 102: **18 passed, 26 failed, 56 ran
out of steps (`capped`, counted apart from failed), 2 errored task-side.**

Broken out by how a task is scored, because they are different task shapes:
**8/55 = 14.5%** on the judge-scored (`llm_boolean`) half, **10/47 = 21.3%** on
the `jmespath`-scored half.

Two cost columns, never added together: **4,000,919 agent tokens** with no dollar
figure, because z.ai publishes no rate for this Coding Plan key; and **$0.0079**
of judging, at OpenAI's published rate on measured usage.

The agent is `glm-4.6` (served `glm-4.6`); the scorer is REAL's own `gpt-4.1`
(served `gpt-4.1-2025-04-14`), at concurrency 3, in 76 minutes.
See [`docs/DECISIONS.md`](docs/DECISIONS.md) entry 16.

## What this does **not** claim

- **Not "unseen real sites."** REAL's sites are deterministic replicas, not the
  live web. The predecessor project made that claim; this one cannot and does
  not. See `docs/DECISIONS.md` entry 1.
- **A score here is not comparable to a live-web score.** Replica sites have no
  ads, cookie banners, modals, lazy loading or A/B tests. They are easier, and a
  number measured here would be flattered by that.

## Why deterministic replicas

Two reasons, in order of importance:

1. **The ablation becomes valid.** Comparing observation-richness arms on the
   live web means the arms see different pages, and that variance is a
   confounder sitting on top of the effect. On deterministic replicas both arms
   see byte-identical pages, so the difference is the thing that was changed.
2. **Wall-clock.** The predecessor lost an eight-hour run that produced nothing,
   and once sat on a single site for nine minutes inside one action.

## Running it

```bash
uv sync          # Python is pinned to 3.12 — see DECISIONS entry 2
./init.sh        # env + lint + tests; fails loudly rather than passing vacuously
```

Requires `ZAI_API_KEY` in `.env` (gitignored, and `init.sh` fails if it is ever
tracked).

## Layout

```
AGENTS.md            build rules and definition of done
feature_list.json    8 features, source of truth for state
docs/DECISIONS.md    every decision and measurement, append-only
init.sh              the verification path
tests/               environment invariants
```

## Predecessor

This replaces `browser-agent-webvoyager`, archived on 2026-07-31 and preserved
at [github.com/sarthakydv/browser-agent-webvoyager](https://github.com/sarthakydv/browser-agent-webvoyager).
Its site-reachability and task-decay audits stand as findings in their own right.

## Licensing

`agisdk` is MIT. The 11 website replicas are **non-commercial research use** —
two different licenses, recorded so they are never conflated.
