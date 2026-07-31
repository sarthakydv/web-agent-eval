# web-agent-eval

A web agent measured on [REAL](https://github.com/agi-inc/REAL) — 112 tasks
across 11 deterministic replica sites.

> **Status: measured, 2026-07-31.** No figure appears in this README that does
> not trace to an entry in [`docs/DECISIONS.md`](docs/DECISIONS.md). Anything not
> yet produced by something that ran stays `TBD`.

## What this measures

| | |
|---|---|
| Success rate, **n = 102**, 25-step cap | **17.6%** (18/102) — against a published **≤41%** baseline |
| Tokens per task | **39,225 mean** (4,000,919 agent tokens over 102 tasks) |

**Deterministic replicas are easier than live sites, so 17.6% is not comparable
to a live-web score.** That qualifier goes with the number wherever it appears.

**The 25-step cap is not what is holding that number down.** 56 of the 102
episodes ran out of steps, so the rate was a lower bound until it was tested:
re-running exactly those 56 at **double the step cap** converted **3**, and 40 of
them burned 50 steps and still did not finish. The same population at 50 steps
comes to **20.6%** — a composite of two runs, quoted with its construction, never
in place of the 17.6% measured at 25. See entry 17.

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

## The ablation: richer observations cost 5x and did not measurably help

Same 102 tasks, same caps, same model — only the observation serializer changed
(entry 17).

| observation richness | passed | rate | agent tokens |
|---|---|---|---|
| `lean` | 18/102 | 17.6% | 4.00 M |
| `rich` | 23/102 | 22.6% | 20.72 M (**×5.18**) |
| delta | +5 tasks | **+4.9 pts** | |

**+4.9 points is inside the noise.** 15 tasks changed verdict, 10 of them toward
`rich`; McNemar exact, two-sided, **p = 0.302**. And the cap-sensitivity run
above measured the noise floor directly: re-running the same tasks under the
same conditions at `temperature=0` moves **17.9%** of them. An ablation chasing a
five-task difference sits underneath that.

Two things the aggregate hides, both in entry 17: the judge-scored and
`jmespath`-scored halves move in **opposite** directions (+14.5 and −6.4 points),
and `rich` hit the 12 000-token observation budget on **72.6%** of its steps — so
what was compared is `lean` against `rich` clipped to that budget.

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
   Worth noting after running it: byte-identical pages removed the *page*
   variance, and a 17.9% run-to-run flip rate remained (entry 17). Determinism
   in the environment is not determinism in the agent.
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
