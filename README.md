# web-agent-eval

**18 of 102 tasks passed — 17.6% — against REAL's published ≤41% ceiling. This
agent scores below the baseline.**

`n = 102`, not 112: the omnizon replica returns HTTP 451 `x-vercel-error:
DMCA_TAKEDOWN`, so its 10 tasks cannot run. That count and that reason travel
with the rate wherever it appears ([`docs/DECISIONS.md`](docs/DECISIONS.md)
entries 5 and 16).

Broken out, because the two halves are different task shapes:

| scored by | passed / n | rate |
|---|---|---|
| judge (`llm_boolean`) | 8 / 55 | **14.5%** |
| `jmespath` | 10 / 47 | **21.3%** |
| **all** | **18 / 102** | **17.6%** |

Of the 102: 18 passed, 26 failed, **56 ran out of steps** (`capped`, counted
apart from failed), 2 errored task-side. Entry 16.

A browser agent under a published ceiling is an ordinary result. What is worth
reading here is that the number is trustworthy and its limits are measured. Every
figure below resolves to a numbered entry in
[`docs/DECISIONS.md`](docs/DECISIONS.md); anything that could not be traced was
left out.

## The three findings that make the number defensible

### 1. The step cap is not the explanation

56 of 102 episodes ended on the 25-step cap, which makes 17.6% a lower bound and
is the first objection anyone reading the raw run would raise. So exactly those
56 tasks were re-run at **double the step cap** — same model, same observation
level, per-step token and wall-clock allowance held constant, its own frozen
manifest (entry 17):

```
converted to a pass     3    v1.networkin-4, v1.staynb-2, v1.zilloft-3
still out of steps     40    every one of them at exactly 50 steps
now terminal, failed   13
errored                 0
conversion rate       3/56 = 5.4%
```

Forty tasks burned fifty steps and still did not finish. And the three
conversions finished at **23, 33 and 23 steps** — two of them inside the original
25-step budget, so the extra budget cannot explain them. **17.6% is a capability
number, not an artefact of the cap.**

Stated as a construction and never as a substitute: the same population at 50
steps is `(18 + 3) / 102 = 20.6%`, a composite of two runs rather than a run.
17.6% over n = 102 is the measured figure and it stands.

### 2. The noise floor is 18%

Ten of those 56 tasks terminated **inside** 25 steps on the re-run, having run out
of steps at 25 the first time — same model, same level, same per-step allowance,
`temperature = 0.0`. The first 25 steps of the re-run are run under exactly the
conditions of the original.

```
terminated inside the old 25-step budget on the re-run:  10 of 56  =  17.9%
two of the ten flipped all the way to a pass
```

**A browser agent at temperature 0 is not deterministic: roughly one episode in
six lands somewhere materially different on a re-run** (entry 17). Byte-identical
pages removed the variance in the *environment*; this is what remained in the
*agent*. It bounds every comparison in this repo, including the splits above.

### 3. The ablation is null, and that is the point

Richer observations, same 102 tasks, same caps, same model — the observation
serializer is the only thing that differs, and `scripts/ablation.py` refuses to
print a delta until it has established that from the two frozen manifests
(entry 17).

| observation level | passed / n | rate | agent tokens |
|---|---|---|---|
| `lean` | 18 / 102 | 17.6% | 4,000,919 |
| `rich` | 23 / 102 | 22.6% | 20,719,779 (**×5.18**) |
| delta | +5 tasks | +4.9 pts | |

15 tasks changed verdict, 10 of them toward `rich`; McNemar exact, two-sided,
**p = 0.302**. **A delta of five tasks is exactly what an 18% flip rate produces
by chance** — finding 2 is measured on this same task set. The honest statement
is that no effect was detected at n = 102: not that richness does nothing, and
not that it helps.

**5.18× the tokens for a difference that does not survive the noise floor.** The
tokens are the one clear result, and they are only a claim about cost, not a
finding about efficiency.

Two things the aggregate hides, both in entry 17: the judge-scored and
`jmespath`-scored halves move in **opposite** directions (+14.5 and −6.4 points on
n = 55 and n = 47 — a lead, not a finding), and `rich` hit the 12,000-token
observation budget on **72.6%** of its steps, so what was compared is `lean`
against `rich` clipped to that budget.

## Cost — two kinds, never summed

| | |
|---|---|
| **Agent** | **4,000,919 tokens** over the 102 scored attempts (mean 39,225; min 0; max 99,960). **No dollar figure**: z.ai publishes no rate for this Coding Plan key, and this project does not estimate one. |
| **Judge** | **$0.007926** — 23 calls, 3,687 prompt + 69 completion tokens at OpenAI's published $2.00 / $8.00 per 1M in/out (rate source: https://developers.openai.com/api/docs/pricing, read 2026-07-31). |

Entry 16. There is no combined total, because one column is dollars and the other
is not convertible into them.

For reference, the other two runs: `rich` cost 20,719,779 agent tokens and
$0.011138 of judging; the 50-step re-run of the 56 capped tasks cost 5,657,354
agent tokens (×1.82 over the same tasks at 25 steps) and $0.001740 (entry 17).

## Scoring provenance

**The agent is `glm-4.6`; the scorer is `gpt-4.1`, REAL's own default judge as
shipped by agisdk.** Requested `glm-4.6`, served `glm-4.6`; requested `gpt-4.1`,
served `gpt-4.1-2025-04-14` from `api.openai.com`.

Scoring the 47 `jmespath` tasks alone would have needed no OpenAI key and would
have published 21.3% — 3.7 points above the real figure. That subset is not a
random sample, so it was rejected before anything ran, and the judge was bought
instead (entries 10, 16). Using the benchmark's own scorer is what keeps the number
comparable to the baseline.

The model string is pinned rather than trusted: `glm-5.1` cannot be pinned on this
endpoint — ask for it and `glm-5.2` answers — which is why the record names what
was *served* on the day and not what was requested (entry 9).

## What this does **not** claim

- **Not "unseen real sites."** REAL's sites are **deterministic replicas** — no
  ads, cookie banners, modals, lazy loading or A/B tests. They are **easier than
  live sites**, so **this score is not comparable to a live-web score** and must
  never be presented as if it were. The predecessor project made that claim; this
  one cannot and does not (entry 1).
- **The ≤41% is a published ceiling, not a head-to-head.** Source: REAL —
  [realevals.xyz](https://www.realevals.xyz),
  [github.com/agi-inc/REAL](https://github.com/agi-inc/REAL),
  [arXiv:2504.11543](https://arxiv.org/abs/2504.11543) (entry 1). What differs
  from this run: the **task set** (102 of the 112 v1 tasks, omnizon excluded), the
  **model** (`glm-4.6`), the **scaffold** (this repo's own episode loop, action
  space and observation serializer, not a leaderboard entrant's agent), and the
  **caps** — the baseline was not measured under a 25-step budget. It is an
  external anchor for the order of magnitude, not a like-for-like comparison.
- **Every result is stated with its caps.** Per episode: **25 steps, 400,000
  tokens, 300 s wall clock** (entry 11; the same three caps are frozen in each
  run's manifest and re-derived by `ablation.py` from the manifests rather than
  taken on trust). Per run: 8,000,000 tokens and 10,800 s, neither approached
  (entries 15, 16). The 50-step run scales the token and wall-clock caps with the
  step budget so that the **per-step allowance is what is held constant** — 16,000
  tokens and 12 s — and all 40 of its caps were step caps (entry 17).
- **One run, one model, one date.** 2026-07-31. Finding 2 measured an ~18%
  run-to-run flip rate, so **single-run per-task results are noisy by
  construction**; the aggregate is what is being claimed, not any individual task's
  verdict. A designed variance run — the same manifest twice at the same caps — is
  named as still open in entry 17 and is not claimed here.
- **`capped` is not folded into `failed`.** "The agent failed 82 tasks" would be a
  different and less true sentence than "18 passed, 26 failed, 56 ran out of
  steps, 2 broke" (entry 16).

## Running it

```bash
uv sync          # Python is pinned to 3.12 — entry 2
./init.sh        # secrets check, lint, tests; fails loudly rather than vacuously
```

`ZAI_API_KEY` (agent) and `OPENAI_API_KEY` (judge) go in `.env`, which is
gitignored — `init.sh` fails if it is ever tracked.

A full run is three commands. The first freezes the manifest — population,
exclusions, caps and a live judge probe with its control — and nothing else ever
writes it; the second re-invokes the runner until a machine-checkable outcome, and
is resumable after a kill because terminal tasks are never re-run; the third
re-derives the score from the records and refuses to agree if they disagree
(entries 7, 16):

```bash
uv run python scripts/preflight.py --run-id myrun --population 102 --concurrency 3 \
    --budget-tokens 8000000 --budget-wall-clock-s 10800
uv run python scripts/supervise.py --run-id myrun --population 102 --concurrency 3 \
    --budget-tokens 8000000 --budget-wall-clock-s 10800
uv run python scripts/score.py --run-id myrun --check
```

`score.py` recomputes the score from `manifest.json` and `records/*.json` alone
and compares it to the stored one; `--check` exits non-zero if they differ.
Budget: about 4M agent tokens and 76 minutes at concurrency 3 for the 102 tasks
(entry 16).

The two comparisons in this README are re-derivable from the stored runs, and
each refuses to print unless the two runs differ in exactly one thing:

```bash
uv run python scripts/ablation.py arms --a full102 --b rich102
uv run python scripts/ablation.py cap  --baseline full102 --higher cap50
```

## Viewing a stored trace

Every episode writes one JSON file — `runs/<run-id>/episodes/<task>.attempt<n>.json`
— holding the caps, the token accounting, the outcome, and one entry per step
(action, URL, reward, usage, observation size, the model's raw reply). No viewer,
just the file:

```bash
uv run python -c "
import json, sys
e = json.load(open(sys.argv[1]))
print(e['task_id'], e['level_name'], e['outcome'], e['steps'], 'steps', e['tokens']['charged'], 'tokens')
for s in e['trace']:
    print(f\"{s['step']:>3}  {s['url'][:40]:40}  {s['action'][:56]}\")
" runs/full102/episodes/v1.gomail-2.attempt1.json
```

```
v1.gomail-2 lean completed 18 steps 45310 tokens
  1  https://evals-gomail.vercel.app/          noop()
  2  https://evals-gomail.vercel.app/          noop()
  3  https://evals-gomail.vercel.app/          click('209')
...
 17  https://evals-gomail.vercel.app/          press('3616', 'Shift+i')
 18  https://evals-gomail.vercel.app/          send_msg_to_user('First email marked as read.')
```

Swap `['action']` for `['raw']` to read the model's reasoning at each step.

**`runs/` is gitignored** — traces are large and regenerable, and the numbers that
matter live in `docs/DECISIONS.md`, not in the artefacts. So that path exists after
you have run something, not on a fresh clone. What *is* committed is
`fixtures/observations/` — real captured pages, viewable offline with no browser,
no network and no API key:

```bash
uv run python scripts/render_observation.py                      # the token table
uv run python scripts/render_observation.py v1.gomail-2_step00 rich   # what the model saw
```

## Why deterministic replicas

Two reasons, in order of importance (entry 1):

1. **The ablation becomes valid.** On the live web the arms of a comparison see
   different pages — different prices, layouts, A/B buckets — and that variance
   sits directly on top of the effect being measured. On deterministic replicas
   both arms see byte-identical pages. Worth noting after running it: that removed
   the *page* variance and an ~18% agent flip rate remained.
2. **Wall clock.** The predecessor lost an eight-hour run that produced nothing,
   and once sat on a single site for nine minutes inside one action. Both lessons
   are why an episode owns a deadline that bounds the step rather than the gap
   between steps (entry 11), and why a batch checkpoints and resumes (entry 7).

The cost of the move is the claim in **What this does not claim**, paid in full.

## Layout

```
AGENTS.md            build rules and definition of done
feature_list.json    the source of truth for scope and state
docs/DECISIONS.md    every decision and measurement, append-only and indexed
init.sh              the verification path
src/web_agent_eval/  episode loop, caps, observation serializer, judge, records
scripts/             preflight, supervise, score, ablation, and the offline probes
tests/               each gate that asserts "clean" ships with a control that
                     must fail
fixtures/            captured observations — evidence, not regenerable
```

## Predecessor

This replaces `browser-agent-webvoyager`, archived 2026-07-31 and preserved at
[github.com/sarthakydv/browser-agent-webvoyager](https://github.com/sarthakydv/browser-agent-webvoyager).
Its site-reachability and task-decay audits stand as findings in their own right.

## Licensing

`agisdk` is MIT. The 11 website replicas are **non-commercial research use** — two
different licenses, recorded so they are never conflated (entry 1).
