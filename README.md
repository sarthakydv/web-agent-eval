# web-agent-eval

A web agent measured on [REAL](https://github.com/agi-inc/REAL) — 112 tasks
across 11 deterministic replica sites.

> **Status: scaffolded, nothing measured yet.** Every number below is `TBD` and
> will stay `TBD` until something actually produces it. No figure appears in this
> README that does not trace to an entry in [`docs/DECISIONS.md`](docs/DECISIONS.md).

## What this measures

| | |
|---|---|
| Success rate over REAL's 112 tasks | `TBD` — against a published **≤41%** baseline |
| Tokens per task | `TBD` |

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
