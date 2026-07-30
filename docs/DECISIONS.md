# Decisions

Append-only. Every number in this repo traces to an entry here, and every entry
records something that actually ran or a decision taken with its reasoning.

---

## 1 — The benchmark is REAL, and "unseen real sites" is no longer claimed

**Date:** 2026-07-31
**Status:** decided before any code existed in this repo

### What changed

This project replaces an archived predecessor (`browser-agent-webvoyager`,
preserved at `.archive/` in the orchestration root and pushed to
`github.com/sarthakydv/browser-agent-webvoyager`). That project measured a web
agent against the **live web** — first WebVoyager, then Online-Mind2Web.

It is now measured against **REAL**: 112 tasks across 11 deterministic replica
sites.

### Why

Not novelty. Wall-clock and measurement quality.

The predecessor recorded its own problem in source
(`scripts/lib/driver.ts:79-90`): an **eight-hour run that produced nothing**, and
a single action that **sat on one site for nine minutes** with every sub-timeout
set to 45 s or less. Features ran ~1 500 lines each. The machine was never the
constraint — live-web latency, hangs and rework were.

The second reason is the stronger one. The planned ablations compare arms. On the
live web the arms see *different pages* — different prices, layouts, A/B buckets —
and that variance is a confounder sitting directly on top of the effect being
measured. On deterministic replicas every arm sees byte-identical pages, so the
difference between arms is the thing that was changed. **The migration makes the
ablation valid, not merely faster.**

### The cost, stated plainly

**The claim "unseen real sites" is dead.** It was the predecessor's
differentiator and it does not survive this move. A replica is a known, static
target. Sandbox sites are also *easier* than real ones — no ads, cookie banners,
modals, lazy loading or A/B tests — so a success rate here is not comparable to
one on the live web and must never be presented as if it were.

What replaces it: **reproducible evaluation against a published baseline.**
REAL publishes a leaderboard and a stated ceiling of **≤41%** success for current
models, so this project's number is anchored to something external rather than
being an unanchored self-report.

### This is the second benchmark change

Recorded rather than hidden. The predecessor moved WebVoyager → Online-Mind2Web
on 2026-07-30 for task decay (its audit found 4/20 tasks unattemptable and Google
Search blocking 43 tasks), then off the live web entirely on 2026-07-31 for the
reasons above. The orchestration root's `docs/STEPS.md` supersedes the first
decision rather than deleting it.

The predecessor's reachability and decay audits stand as findings in their own
right and remain citable from the archived repo.

### Licensing — two different licenses, do not conflate them

- **`agisdk` (the SDK): MIT.** Confirmed from its `pyproject.toml` classifiers.
- **The 11 website replicas: non-commercial research use.** They are described as
  deterministic simulations built for academic benchmarking, containing no
  proprietary code, content or branding of the original services.

Fine for a portfolio and research project. It would not be fine for commercial
use, and that distinction is recorded here so it is never discovered later.

### Sources

- https://github.com/agi-inc/REAL
- https://www.realevals.xyz
- https://arxiv.org/abs/2504.11543

---

## 2 — Python is pinned to 3.12

**Date:** 2026-07-31

`agisdk` declares `requires-python = ">=3.9"`, so 3.14 is not formally excluded.
It was still rejected. The system interpreter on this machine is **3.14.6**,
which is very new, and `agisdk` pulls `numpy`, `gymnasium`, `ray` and `lxml` —
compiled dependencies that historically lag new interpreter releases. Pinning
costs nothing here and removes a whole class of failure that would otherwise be
indistinguishable from a real bug during `feat-001`.

`uv sync --python 3.12` resolved and installed cleanly:

```
python: 3.12.12
agisdk: installed
REAL harness: True
attrs: ['AbstractAgentArgs', 'Agent', 'browsergym', 'demo_agent', 'harness',
        'hello', 'logging', 'tasks']
```

### Install method — supersedes the README

REAL's own README says `pip install -e ./` from a clone. That is unnecessary:
**`agisdk` is published to PyPI**, and the published version (**0.3.5**) is
*newer* than the version declared in the repository's `main` branch `pyproject.toml`
(0.1.20). This project depends on the PyPI release and does not vendor a clone.

---

## 3 — What `feat-001` must still answer

Recorded here so the gate's purpose survives into the session that runs it.
Three questions could not be answered from documentation and must not be
answered by inference:

1. **Does `agisdk` accept a custom OpenAI-compatible `base_url`,** so z.ai's GLM
   can drive it? It depends on `openai>=1.0.0`, which makes this *likely* — but
   likely is not measured, and the whole project runs on GLM.
2. **Are the 11 replica sites served locally or hosted at realevals.xyz?** This
   decides how much of the speed gain from leaving the live web is actually
   realised. Hosted still buys determinism, no CAPTCHAs and no decay; it does not
   buy freedom from network latency.
3. **Does local scoring require a leaderboard key?**

If GLM cannot be wired up, that is a scoping conversation about model and cost —
**not** a licence to switch to a paid OpenAI or Anthropic model. GLM is the
subject of this project, not an implementation detail.
