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

---

## 4 — `feat-001` [GATE] passed: GLM drives agisdk, one task scored 1.0

**Date:** 2026-07-31
**Model:** `glm-4.6` via z.ai
**Task:** `v1.gomail-2` — "Mark the first email in the Inbox as read."
**Result:** `cum_reward = 1.0`, 9 steps, 35.4 s wall clock, 20 931 GLM tokens.

Reproduce with `uv run python scripts/run_gate.py`.

### Q1 — does `agisdk` accept a custom OpenAI-compatible `base_url`? **Yes, via
`agentargs`. Not via `model=`.**

The distinction matters and the plan's inference was only half right.

`harness(model="...")` builds the built-in `DemoAgent`, which routes on
**model-name prefix** and exposes no `base_url` at all
(`demo_agent/basic_agent.py:104-340`): `gpt-`/`o1`/`o3` → OpenAI, `openrouter/`
→ a hardcoded OpenRouter URL, `local/` → a hardcoded `http://localhost:7999/v1`,
`claude-`/`sonnet-` → Anthropic, anything else → `ValueError: Model ... not
supported`. GLM cannot go through that path.

`harness(agentargs=...)` takes any `AbstractAgentArgs`, and that agent
constructs its own client. That is the seam this project uses
(`src/web_agent_eval/gate_agent.py`):

```
client base_url : https://api.z.ai/api/coding/paas/v4/
model           : glm-4.6
direct probe    : content='ok' model=glm-4.6 usage=12 tokens
agentargs       : GateAgentArgs, AbstractAgentArgs=True
made agent      : GateAgent, REAL Agent=True
```

### The z.ai key is a Coding Plan key, and the two base URLs are not interchangeable

This was nearly mistaken for "GLM cannot be wired up". The documented
pay-as-you-go endpoint rejects this key outright. Probed directly:

```
paas/v4 + REAL key      : HTTP 429 {"error":{"code":"1113","message":"Insufficient balance or no resource package. Please recharge."}}
paas/v4 + BOGUS key     : HTTP 401 {"error":{"code":"401","message":"token expired or incorrect"}}
coding/paas/v4 + REAL   : HTTP 200 {"choices":[{"finish_reason":"length",...
anthropic + REAL        : HTTP 200 {"id":"msg_2026...","model":"glm-4.6","content":[{"type":"text","text":"OK."}]...
```

The bogus-key row is the one that settles it: a bad key gets **401**, this key
gets **429**. The key authenticates fine — it simply has no entitlement on the
pay-as-you-go plan. `https://api.z.ai/api/coding/paas/v4/` is the endpoint the
plan covers, and it is OpenAI-compatible.

Two consequences recorded now rather than rediscovered later:

- **`glm-4.6` reasons by default** and will spend the entire `max_tokens` budget
  on thinking it never returns — the first probe came back with
  `finish_reason: "length"` and `content: ""`. This project sends
  `extra_body={"thinking": {"type": "disabled"}}`.
- **Usage numbers come back on every response** (`prompt_tokens`,
  `completion_tokens`, `total_tokens`), so `feat-005` can sum real tokens rather
  than estimate them.

### Q2 — local or hosted? **Hosted, on Vercel. Nothing is served locally.**

Each task config carries its own absolute start URL, read straight from the
installed package:

```
task            : v1.gomail-2
start_url       : https://evals-gomail.vercel.app
host            : evals-gomail.vercel.app
resolves to     : ['216.198.79.131', '64.29.17.131']
is localhost    : False
WEBCLONE_URL env: None  (unset => config URL is used)
reachable       : True  (0.15s round trip)
```

All 11 sites are `https://evals-<site>.vercel.app`, **not** `realevals.xyz` —
that domain is the leaderboard, not the sites. There is no bundled server and no
docker-compose in the package; `WEBCLONE_URL` can override the host, but nothing
ships to point it at.

**So the answer to "how much of the speed gain is realised" is: less than hoped.**
Network latency stays. The migration still buys determinism, no CAPTCHAs and no
task decay — which per entry 1 was always the stronger reason — but it does not
buy freedom from the network. Measured round trips to the 11 hosts on this
machine ranged 0.13 s to 2.37 s.

### Q3 — does local scoring need a leaderboard key? **No.**

The run above used `leaderboard=False, run_id=None, api_key=None`, with no
`REAL_API_KEY` and no `RUNID` in the environment, and returned a real score:

```
REAL_API_KEY set: False
RUNID set       : None
eval types      : ['jmespath']
harness call    : leaderboard=False, run_id=None, api_key=None
...
✅ ✅ email marked as read: jmespath query, is_correct: True
📊 Task Results - ✅ Task Completed Successfully!  Reward: 1.0  Time: 35.39s
```

`run_id` defaults to `'0'` and `webclones/base.py:348` submits to the leaderboard
only when `run_id != '0'`, so scoring and submission are independent paths. A key
is needed to appear on the public leaderboard, and for nothing else.

**But there is a second key, and it is not the leaderboard's.** Scoring is not
uniformly local: `evaluate.py:223` grades `llm_boolean` evals with an LLM judge
that `WebCloneEvaluator` **hardcodes to OpenAI `gpt-4.1`** through a bare
`OpenAI()` client (`webclones/utils.py:14-21`). **60 of the 112 v1 tasks have at
least one `llm_boolean` eval** and will hit OpenAI, not z.ai. `gomail-2` was
chosen for this gate precisely because its single eval is `jmespath` — a
deterministic query over the site's own `/finish` state — so the 1.0 above owes
nothing to any judge. This is a live cost and comparability question for
`feat-005`, flagged here, not answered here.

### The scoring is real, and it failed before it passed

Not a first-try success, which is the point of recording it. Four runs, all
stored under `runs/gate/`:

```
2026-07-31_02-05-42  reward=0    steps=0   terminated=None   err=True
2026-07-31_02-06-42  reward=0.0  steps=12  terminated=False  err=False
2026-07-31_02-08-50  reward=0.0  steps=12  terminated=False  err=False
2026-07-31_02-10-55  reward=1.0  steps=12  terminated=True   err=False
```

- Run 1 died on a Playwright browser mismatch: `agisdk` pins Chromium build
  1228 and the machine had 1234. `uv run playwright install chromium` fixes it,
  and it is now a setup step.
- Runs 2 and 3 scored 0 for a reason worth keeping. Handing browsergym the
  model's whole reply does not work: its parser scans the **entire string**,
  pyparsing skips whitespace, and so ordinary prose parses as a function call —
  `"the checkbox is already checked (checked='true')"` becomes
  `checked('true')`, and the step dies with "Received a multi-action". Both of
  those strings are now regression tests in `tests/test_gate_agent.py`.
  `feat-002` and `feat-003` inherit this: **the action must be extracted, never
  passed through.**

`GateAgent` is gate scaffolding only. `feat-002` owns the observation serializer
and `feat-003` owns the loop and its caps; nothing in it is a design decision for
either.

---

## 5 — One of the 11 sites has been taken down, and it costs 10 of the 112 tasks

**Date:** 2026-07-31

`evals-omnizon.vercel.app` — the Amazon replica — returns **HTTP 451** with
`x-vercel-error: DMCA_TAKEDOWN`. Three consecutive probes, not a blip:

```
attempt 1: HTTP 451
attempt 2: HTTP 451
attempt 3: HTTP 451

This content has been blocked for legal reasons
DMCA_TAKEDOWN

HTTP/2 451
x-vercel-error: DMCA_TAKEDOWN
```

The other ten hosts answered 200 (gocalendar 308 → 200 after redirect):

```
dashdish 200 | fly-unified 200 | gocalendar 308 | gomail 200 | networkin 200
omnizon 451  | opendining 200  | staynb 200     | topwork 200 | udriver 200
zilloft 200
```

**10 of the 112 v1 tasks are omnizon tasks and cannot run.** Per `feat-006`'s own
rule, that count and this reason must be published beside any success rate, and
the denominator must be stated — `n = 102`, not 112, unless the site returns.

This is the deterministic-replica benchmark's version of the task decay that
killed the predecessor's WebVoyager set, and it is worth noting that it happened
anyway: determinism protects against pages *changing*, not against a host
*disappearing*. Entry 1's framing survives, but "no decay" was too strong.

Combined with entry 4's judge finding: of the 112 v1 tasks, 10 are unreachable,
60 need an OpenAI judge to be scored, and **47 are both reachable and scorable
with no API key but z.ai's**.
