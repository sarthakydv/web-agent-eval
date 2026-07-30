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

---

## 6 — `feat-002`: the observation serializer, and how tokens are counted

**Date:** 2026-07-31
**Reproduce:** `uv run python scripts/render_observation.py` (offline),
`uv run python scripts/token_check.py` (one real z.ai call per fixture/level).

### The fixtures are real captures, and the gate did not leave any

`feat-002`'s tests run against observations that came off a live agisdk run, not
against a page anybody wrote by hand. That distinction is the whole value of the
tests: a serializer checked against a hand-written DOM is a test of the
hand-written DOM.

The gate's four stored runs under `runs/gate/` do **not** contain an
observation. They hold `summary_info.json`, `experiment.log`, `exp_args.pkl`,
`goal_object.pkl.gz` and `finish_state.json`; the agent's own
`v1.gomail-2.trace.jsonl` records url, reply, action and usage per step. No DOM,
no accessibility tree, no screenshot. **So observations were captured fresh** —
`scripts/capture_observations.py`, two tasks, ten steps, of which five are
committed:

```
fixtures/observations/v1.gomail-2_step00.json.gz      7,417B   +   14,002B png
fixtures/observations/v1.gomail-2_step02.json.gz     89,432B   +  635,368B png
fixtures/observations/v1.gomail-2_step03.json.gz     24,223B   +  346,487B png
fixtures/observations/v1.staynb-1_step00.json.gz    160,564B   +  599,981B png
fixtures/observations/v1.staynb-1_step02.json.gz    182,344B   +  285,091B png
```

Each is the raw observation browsergym handed the agent — the full CDP DOM
snapshot, the merged accessibility tree, the extracted element properties, the
goal, the URLs and the 1280x720 screenshot as PNG. Two sites, deliberately, so
the serializer is not tuned to one page shape:

```
v1.gomail-2_step00   ax_nodes=  13  dom_strings= 267   page still loading
v1.gomail-2_step02   ax_nodes=1498  dom_strings=2651   inbox, loaded
v1.gomail-2_step03   ax_nodes= 237  dom_strings= 837   after click('209')
v1.staynb-1_step00   ax_nodes=3588  dom_strings=4162   landing page
v1.staynb-1_step02   ax_nodes=4074  dom_strings=4804   after a date fill
```

`gomail-2_step00` is kept precisely because it is degenerate: 13 nodes, a page
that had not finished loading. That is why the gate's first two actions were
`noop()`, and it is the kind of observation nobody writes by hand.

### The seam: richness is a data object, not a branch

`Richness` is a frozen dataclass; `serialize(obs, level)` takes one. Two levels
ship, and they differ only in the fields of that object:

```
lean : axtree(filter_visible_only=True, filter_with_bid_only=True, skip_generic=True)
rich : axtree(filter_visible_only=True, skip_generic=True, with_center_coords=True,
              with_clickable=True, with_visible=True) + pruned-html + page-context
              + screenshot-note
```

`feat-007` varies this object and nothing else. A caller-defined level works
without touching `serialize()`, and there is a test that asserts exactly that —
if a new rung required a code change, the ablation would be comparing a code
change too.

**What does not vary with richness: the goal, the URL and the last action's
error.** They are rendered at every level. Removing them would not make an
observation poorer, it would change the task the agent was given, and it would
confound the ablation this seam exists for.

### The screenshot contributes its dimensions and nothing else

Stated plainly rather than glossed. `glm-4.6` through z.ai's coding plan is
text-only, so no pixels are sent. The screenshot is captured and committed
because it is part of the observation and a vision model would use it, but at
`rich` it renders as one line — `1280x720 screenshot captured and stored, but
not sent` — and pretending otherwise would misdescribe what the model saw.

### The budget: 12 000 tokens, and there are two numbers for it

**The claim is provider-side: no rendered observation exceeds 12 000 tokens as
z.ai counts them.** Enforcement has to be local, because a unit test cannot bill
an API call, and the local tokenizer is not GLM's. So:

```
PROVIDER_TOKEN_BUDGET     = 12 000     the claim, in z.ai's units
MEASURED_LOCAL_UNDERCOUNT = 1.022      worst case measured, see the table below
TOKEN_BUDGET              = 11 741     what the code enforces, locally
```

12 000 is itself a measured choice: across the five fixtures the richest
accessibility tree tops out near 11 000 tokens before any HTML, and the leanest
sits near 2 000. A budget much below that truncates the rich arm on every page
and turns `feat-007` into a comparison of two truncations. Enforcement is by
line-wise truncation with the count of dropped lines reported, never by hope:

```
fixture                    level   tokens  budget   ok  truncated
v1.gomail-2_step00         lean        88  11,741 True  -
v1.gomail-2_step00         rich       550  11,741 True  -
v1.gomail-2_step02         lean     2,009  11,741 True  -
v1.gomail-2_step02         rich    11,731  11,741 True  html -508 lines
v1.gomail-2_step03         lean       873  11,741 True  -
v1.gomail-2_step03         rich     9,433  11,741 True  -
v1.staynb-1_step00         lean     1,231  11,741 True  -
v1.staynb-1_step00         rich    11,734  11,741 True  axtree -147 lines, html -414 lines
v1.staynb-1_step02         lean     2,309  11,741 True  -
v1.staynb-1_step02         rich    11,738  11,741 True  axtree -519 lines, html -757 lines
```

The two arms are 4x–6x apart in tokens on a loaded page, which is the cost side
of what `feat-007` will trade against success rate.

### How tokens were counted, and where that count is wrong

**Locally: `tiktoken`, encoding `cl100k_base`.** That is not GLM's tokenizer —
z.ai publishes none for `glm-4.6` — so the local count is an approximation, and
an unchecked approximation is a guess with a library behind it.

It was checked. `scripts/token_check.py` sends two real chat completions per
fixture/level that are byte-identical apart from the observation text, and
differences their `prompt_tokens`: identical framing on both sides, so the
difference is z.ai's own count of exactly the serializer's output.

```
model            : glm-4.6 via https://api.z.ai/api/coding/paas/v4/
framing baseline : prompt_tokens=11 for the fixed system message plus '.'

fixture                    level   cl100k    o200k      glm  glm/cl100k  glm/o200k
v1.gomail-2_step00         lean        88       88       88       1.000      1.000
v1.gomail-2_step00         rich       550      552      555       1.009      1.005
v1.gomail-2_step02         lean     2,009    2,004    2,054       1.022      1.025
v1.gomail-2_step02         rich    11,731   12,141   11,956       1.019      0.985
v1.gomail-2_step03         lean       873      871      873       1.000      1.002
v1.gomail-2_step03         rich     9,433    9,470    9,523       1.010      1.006
v1.staynb-1_step00         lean     1,231    1,244    1,242       1.009      0.998
v1.staynb-1_step00         rich    11,734   12,570   11,858       1.011      0.943
v1.staynb-1_step02         lean     2,309    2,322    2,330       1.009      1.003
v1.staynb-1_step02         rich    11,738   12,382   11,979       1.021      0.967
TOTAL                              51,696   53,644   52,458       1.015      0.978
```

`cl100k_base` **understates** z.ai's count by 1.5% in aggregate and by at most
2.2% on any single rendering. `o200k_base` overstates by 2.2% in aggregate and
swings wider per case (0.943 to 1.025), so `cl100k_base` is the encoding this
project uses. The 2.2% worst case is where `MEASURED_LOCAL_UNDERCOUNT` comes
from, and the largest provider-side count observed after applying it is **11 979
tokens — under the 12 000 the claim states**. The disagreement is reported here
rather than resolved in the flattering direction.

**This is not the same measurement as entry 4's 20 931 tokens, and the two must
not be mixed.** That figure was z.ai's `usage` summed over a whole episode —
every prompt, every completion, all nine steps of `v1.gomail-2`. It was never a
local count of one observation. Two different accounting lines survive from here
on: budget accounting is local, deterministic and testable offline; cost
accounting (`feat-005`) is the provider's `usage` field summed from responses
that actually happened, and is never estimated locally.

### Tests: 38 of them, and no browser

`tests/test_observation.py` and `tests/test_tokens.py` read the committed
fixtures and count tokens. They start no browser and make no network call —
`env -u ZAI_API_KEY uv run pytest tests/test_observation.py tests/test_tokens.py
-q` gives `38 passed in 2.26s`. `tiktoken`'s BPE file is cached inside the repo
at `.cache/tiktoken/` (gitignored) so a cleared system temp directory cannot
silently turn a unit test into a download.

### Out of scope, deliberately

No agent loop, no caps, no retries — `feat-003`. No action parsing: the gate's
prose-parsed-as-a-multi-action finding lives in `extract_action` on the action
side and stays there. `runs/` stays gitignored; `fixtures/` is tracked, because
a capture is evidence and cannot be regenerated identically.

---

## 7 — The run loop: what it may retry, and what it may not call a failure

**Date:** 2026-07-31
**Status:** decided **before** `feat-004` exists, because every rule here is one
that is impossible to apply honestly after seeing the results.

`feat-006` runs for hours unattended. That makes the batch runner a loop that
supervises itself, and a self-supervising loop can quietly manufacture a wrong
number in three ways. Each is closed here.

### The manifest is frozen at run start, and it names its own population

`runs/<run-id>/manifest.json` is written before the first task and never edited:
the task ids to be attempted, the population they were drawn from, and every
exclusion with its reason. A denominator that emerges from which tasks happened
to fail is not a denominator.

Entry 5 leaves **three defensible populations** and the choice belongs to
`feat-006`, not to the runner:

- **112** — the full v1 set.
- **102** — reachable; excludes the 10 omnizon tasks (HTTP 451, DMCA takedown).
- **47** — reachable *and* scorable with no key but z.ai's; the other 60 have at
  least one `llm_boolean` eval that calls an OpenAI judge (entry 4).

Whichever is run, the manifest records which and why, and the rate is published
with that `n` beside it.

### A provider error is not a task failure

`429`, `401`, an entitlement change, or a connection reset from z.ai says
nothing about whether the agent can do the task. The gate already met one of
these (entry 4: this key gets `429` on `paas/v4` and `200` on
`coding/paas/v4` — a difference in entitlement, not in capability), and an
unattended multi-hour run is exactly where a rate cap turns into a wall of
zero-reward episodes that look like agent failures.

So the runner records `provider_error` as a **non-terminal** status. The task
stays unattempted, and the supervisor may retry it. If provider errors are all
it is getting, it **stalls and reports** rather than filling the manifest with
zeros.

Terminal statuses are `passed`, `failed`, `capped` and `errored` (task-side —
the agent ran and something in the episode broke). A `capped` episode is scored
by agisdk like any other, which will normally be `0`, but it is **counted
separately and published beside the rate**: "of the n tasks, k ended on a cap"
is a different statement from "the agent failed k tasks", and collapsing them
overstates what was measured.

### Attempts append; the score reads the first terminal attempt

`runs/<run-id>/results.tsv` is append-only and holds one row per **attempt**,
including retried ones. The success rate is computed from each task's **first
terminal attempt**. Retries exist to survive provider errors and interruptions,
never to re-roll a task until it passes — a loop that retries until success and
scores the last attempt measures how many retries it was given, not how capable
the agent is.

### The supervisor stops on a condition, not on a judgement

`scripts/supervise.py` re-invokes the runner until one of three machine-checkable
outcomes, and never runs unbounded:

| Exit | Condition |
|---|---|
| `0` | every manifest task has a terminal record |
| `1` | K consecutive rounds added no new terminal record — **stalled** |
| `2` | the token or wall-clock budget for the run was exceeded |

It is idempotent: run it again after a completed run and it prints the summary
and changes nothing. Each round appends a line with what it attempted, what
became terminal, and any backoff it applied.

### What is deliberately *not* looped

**No autonomous coding loop in this repo.** The remaining features are
measurement-integrity decisions — the denominator, the retry rule, what a cap
means — and none of them has a machine-checkable stopping condition. The
evaluator here is agisdk's own programmatic checks, which is stronger than a
model judging a model; keeping it that way means the loop supervises **runs**,
not **work**. The archived predecessor's rule stands: a model labelling its own
failures makes the number meaningless.

---

## 8 — The tracker enforces its own rules, and each rule was tested by breaking it

**Date:** 2026-07-31
**Status:** harness change; no measurement in this entry

`feature_list.json` sets `verification_required` and every feature carries a
`verification` command written before its work starts. `init.sh` now enforces
three rules that it previously only described:

1. every feature has a non-empty `verification` command,
2. a `done` feature has non-empty `evidence`,
3. at most one feature is `in-progress`.

A status field an agent can set on its own, with no command behind it and no
output pasted under it, is an opinion. But a rule is only as good as its
enforcement, so each of the three was **broken deliberately** in a scratch copy
of `feature_list.json` and confirmed to fail:

```
(a) verification field deleted    FAIL: no verification field: feat-003
(b) done, evidence set to ""      FAIL: done with an empty evidence field: feat-001
(c) two features in-progress      FAIL: one feature at a time, but in-progress: feat-003, feat-004
```

All three exited **1**, each naming the problem. The file was then restored and
confirmed byte-identical by checksum. `.github/workflows/ci.yml` carries a second
copy of the same logic; it was extracted verbatim from the workflow and run
against the same three broken files, exiting `1` each time and `0` on the real
file. Validating one copy would have left the other unproven.

### CI runs the offline half of `init.sh`

Everything in the workflow passes with no key, no browser and no network round
trip to the replica sites: the tracked-`.env` check, the interpreter pin and
`agisdk` import, `ruff`, the tracker rules, and the test suite with the key
unset. The parts that need `ZAI_API_KEY` — the gate run, the capture scripts —
are deliberately excluded, because a CI job that needs a secret to be honest is
a job that gets skipped.

### Two ways a scan reported "clean" while it was not

Both were caught only because every negative result was preceded by a positive
control — a search for a string known to be present, to prove the pipeline was
live before trusting it to find nothing. Recorded here because this repo's whole
premise is that a check which cannot fail is worse than no check:

- `grep` on the development machine is **ugrep**, which honours `.gitignore`. A
  recursive secret scan therefore skipped `.env` itself — the one file it most
  needed to read. Pass filenames explicitly, or `--no-ignore-files`.
- **`git grep -E` does not support `\b`** as a word boundary (POSIX ERE), so a
  content scan for `\bcv\b` matched nothing regardless of content. Use
  `--perl-regexp`, or fixed strings with `-F`. Note also that `git grep -I`
  skips binary blobs, so the gzipped and PNG fixtures had to be decompressed
  before they were actually searched.

### The repo is public from this date

First push: `main` at the commit that introduced this entry's harness changes,
to `github.com/sarthakydv/web-agent-eval`, with CI green on the first run. Before
that push, history was rewritten once to drop a single out-of-scope line from the
root commit's `progress.md`; the commit whose only content was removing that line
became empty and was pruned. The published tree is byte-identical to the
pre-rewrite tree — both hash to `cc8e3e5351e37ea52b1a30de103ef3118befdcaf` — so
the rewrite changed one intermediate state and no published content.

The pre-rewrite refs (`refs/original/*` and a backup branch) were then deleted,
the reflog expired and `git gc --prune=now` run, after confirming that each old
commit was content-identical to its rewritten counterpart except the root's single
deleted line, that nothing was unpushed, and that no stash existed. `main` is now
the only local branch, so no `git push --all` can publish an unintended ref.
