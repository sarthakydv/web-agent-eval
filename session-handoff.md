# Session Handoff — web-agent-eval (P3)

## Current Objective

- **Goal:** Measure a web agent on REAL (112 tasks, 11 deterministic replica
  sites) with every number traceable to something that actually ran.
- **Current status:** `feat-001` `[GATE]` **passed**, `feat-002`, `feat-003` and
  `feat-004` **done**. One REAL task ran end to end on GLM and scored **1.0**;
  the serializer renders an observation at a parameterised richness level under a
  measured token budget; the episode loop runs under three independent caps; and
  the **batch runner and supervisor now drive that loop unattended** — resuming
  after a `SIGKILL`, refusing to call a `429` a task failure, and stopping on a
  budget rather than running on.
- **Next is `feat-005`, and it is blocked on a human step:** the
  `OPENAI_API_KEY` placeholder in `.env` must be filled — entry 10.
- **Branch / commit:** `main`, tracking `origin/main` at
  `github.com/sarthakydv/web-agent-eval` (**public**). CI green.

## Completed This Session (`feat-004` — the batch runner and the supervisor)

- [x] **`src/web_agent_eval/manifest.py`** — the frozen manifest. Populations
      112 / 102 / 47 derived from the installed task configs (not hardcoded),
      every exclusion carrying its reason, and a resume that changes population,
      task ids, caps, model or entrypoint is **refused**, not silently honoured.
- [x] **`src/web_agent_eval/records.py`** — atomic terminal records
      (`tmp` + `fsync` + `os.replace`), the append-only `results.tsv` (one
      `os.write` to an `O_APPEND` fd, safe across worker processes), the
      provider-error classifier, and the summary that reads each task's **first**
      terminal attempt.
- [x] **`src/web_agent_eval/batch.py`** — one round: spawn one process per task,
      at most N at once, never two on the same site, halve concurrency on a
      provider error and recover one worker per five clean episodes.
- [x] **`scripts/run_batch.py`** — one round, exit 2 on the run budget.
- [x] **`scripts/supervise.py`** — rounds until exit 0 / 1 / 2, bounded by
      `--max-rounds`, idempotent on a completed run, no model anywhere in the path.
- [x] **`scripts/concurrency_probe.py`** — the burst and sustained probes.
- [x] **50 new tests** (`tests/test_resume.py`, `tests/test_supervise.py`,
      `tests/fake_episodes.py`), none of which start a browser, make a network
      call or need an API key. 126 in total.

## The probe: the published concurrency limit does not apply to this key

Run **before any batch code was written**, as entry 7 requires.

| Probe | Result |
|---|---|
| Burst, simultaneous completions at N = 2, 3, 4, 5, 6, 8, 10, 12 | **every one accepted, none rejected**, latency flat |
| Sustained, 3 workers, one call each per 4 s, 7 minutes | **315 calls, 315 ok, 0 rejected**, no latency drift |

z.ai publishes a concurrency limit of 3 for `glm-4.6`; that is the pay-as-you-go
figure and this is a Coding Plan key, which entry 4 already proved is a different
product. No `x-ratelimit-*` headers are exposed, so load is the only instrument.

**What it rules out:** a limit of 3, and any quota inside 315 calls / 7 minutes.
**What it does not:** a quota at hour two. A full 47-task run is only of order
500–1 000 model calls, so probing that far would cost as much as the run it
protects. The answer to the residual risk is structural, not a bigger probe —
a provider error is non-terminal, the supervisor exits 1 as stalled rather than
filling the manifest with zeros, and the run resumes.

**The default stays 3.** The measurement lifted the provider constraint, not the
site rule or comparability. Raising it is a human scoping decision — entry 12.

## The rule that was not in entry 7: retire a capped worker

`feat-003`'s wall-clock cap is `future.result(timeout=...)` on the episode's own
worker thread. That bounds the **wait**, and Python cannot kill a thread — so
when the cap fires the thread is **abandoned, not terminated**, and may still be
driving a browser. REAL scores by **diffing environment state**, so letting that
process take another task would contaminate the next task's diff and produce a
*silently wrong score*: the exact class of error entry 7 exists to prevent.

- **One process per task** — reuse is structurally impossible.
- **A `wall_clock` cap gets a 1 s grace, then `SIGKILL`**, where a normal worker
  gets 10 s to exit on its own.
- **Its site stays reserved until the process is confirmed dead.**

Verified by breaking it: removing the kill fails the test in 3.6 s
(`'killed': False`), **and then `pytest` itself cannot exit**, because
`multiprocessing` joins non-daemon children and the abandoned thread keeps the
child alive for its full hour. The hang is the bug.

## Verification Evidence

| Check | Command | Result |
|---|---|---|
| **(1) tests** | `uv run pytest -q -k 'resume or supervise'` | `50 passed, 76 deselected in 118.18s` |
| **(2) kill** | 6-task batch `SIGKILL`ed with 2 records down and 3 workers in flight, then restarted with the identical command | restart: `2 of 6 already terminal (skipping them)`, re-ran none, both records **byte-identical** (sha256), `EXIT 0` |
| **(3) stall** | same command with `ZAI_BASE_URL=…/paas/v4/` (entry 4's real 429) | `EXIT 1 (STALLED)`, **no `records/` directory at all**, 4 non-terminal `provider_error` rows |
| **(4) budget** | `--budget-tokens 60000` on a 6-task run | `EXIT 2 (BUDGET)` mid-run at 85 589 tokens, 3 terminal records intact |
| no-op | `supervise.py` again on the completed run | `already complete — nothing to do`, content+mtime digest **identical** |
| Lint | `uv run ruff check .` | `All checks passed!` |
| Full path | `./init.sh` | `126 passed`, `=== All checks passed ===` |

**Every check has its control**, per the standing rule — a supervisor that always
exits 1 passes the stall test:

| Check | Control — must NOT fire | Result |
|---|---|---|
| resume | a fresh run | `0 of 6 already terminal`, runs all six |
| stall | the same tasks on the working endpoint | `EXIT 0`, 2 terminal records |
| budget | the same run resumed at 400 000 tokens | `EXIT 0`, finishes |
| tests | three rules broken on purpose | each turns the suite red (below) |

### Three deliberate breaks, to prove the suite is not vacuous

| Break | Result |
|---|---|
| remove the `SIGKILL` that retires a capped worker | fails in 3.6 s on `'killed': False`, then `pytest` will not exit |
| ignore existing terminal records (resume off) | `assert 0 == 3` (skipped), and a record file is overwritten by attempt 2 |
| classify a 429 as a task failure | `assert {'errored': 1} == {'provider_error': 1}` |

## 11 real episodes ran, and they are not a success rate

4 passed, 4 failed, 3 capped — over task sets chosen to exercise the mechanics,
`n = 11`, population `explicit`. **It must never be quoted as a score.** Two
things in it are worth `feat-006`'s attention:

- **Every cap that fired in a live episode was the 25-step cap**, at the `lean`
  level. One episode spent 74 918 tokens; the range was 8 940 – 74 918 tokens
  and 23.5 – 109 s at concurrency 2–3 (and per entry 7 a per-task wall clock at
  N > 1 is not comparable to a sequential one).
- **No wall-clock cap fired in a real run**, so the abandoned-thread rule is
  verified against a fake that reproduces the condition exactly
  (`tests/fake_episodes.py`, `v1.wedge-*`), not a live browser hang.

## Decisions Made

Entry 12 was appended this session; 1–11 predate it.

12. **`feat-004`: what this key really allows, and the batch that survives being
    killed.** The burst and sustained probe numbers and what they do and do not
    rule out; why the default stays 3 anyway; the retire-a-capped-worker rule and
    the state-diff contamination it prevents; the table of entry 7's rules and
    where each lives; the two orderings that carry weight (attempt row before
    terminal record, rounds numbered across restarts); and the four checks with
    their controls.

## Blockers / Risks

- **`feat-005` is blocked on a human step.** `OPENAI_API_KEY` in `.env` is an
  empty placeholder. 60 of the 112 tasks have an `llm_boolean` eval that agisdk
  grades with a hardcoded OpenAI `gpt-4.1` judge (entries 4 and 10). Without it
  the population is **47**, not 102, and the denominator stops being comparable
  to REAL's published baseline. `--population 47` runs today with z.ai alone.
- **`feat-006`'s denominator is at most 102, never 112.**
  `evals-omnizon.vercel.app` is DMCA-taken-down (451). The count and reason must
  be published beside any rate — entry 5.
- **A quota beyond 315 calls / 7 minutes is not ruled out.** The design survives
  it (non-terminal provider errors, stall exit, resume) but a long unattended run
  should be checked on rather than assumed.
- **The agent capped on steps in 3 of 11 live episodes.** Whether 25 steps at the
  `lean` level is the right operating point is `feat-006`'s and `feat-007`'s
  question, not something to change quietly mid-measurement — the caps are held
  constant across arms (entry 11).
- **Replica sites are easier than live ones.** A score here is not comparable to
  a live-web score.

## Next Session Startup

1. Read `AGENTS.md`, then **only `feat-005`'s entry** in `feature_list.json`,
   then the index at the top of `docs/DECISIONS.md` — entries 10 and 4 for the
   judge, 5 for the populations, 12 for how a run is driven. Neither file is read
   end to end.
2. Run `./init.sh` — expect `126 passed` and all checks passed. It takes ~2
   minutes now: `feat-004`'s tests spawn real worker processes.
3. If the browser is missing: `uv run playwright install chromium` (agisdk pins
   Chromium build 1228; a mismatch fails with an error that does not look like a
   version problem).
4. **Fill `OPENAI_API_KEY` in `.env` first, or take `feat-005` knowing the
   population is 47.** That is a human decision, not the runner's.

Nothing is outstanding. `main` is the only local branch and `main == origin/main`.

## Recommended Next Step

`feat-005`, evaluation and cost recording, once the key question above is
settled. What carries into it from this session:

- **The runner already records the cost.** `results.tsv` has `tokens` per
  attempt (provider `usage`, not an estimate), and each terminal record carries
  `reward`, `steps`, `tokens`, `wall_clock_s` and which cap fired. `feat-005`
  should read those rather than re-derive them.
- **The rate reads each task's first terminal attempt**, and
  `records.summarise()` already does it. Retries exist to survive interruptions,
  never to re-roll a task until it passes.
- **`capped` is counted and published separately from `failed`.** "Of the n
  tasks, k ended on a cap" is a different statement from "the agent failed k",
  and collapsing them overstates what was measured — entry 7.
- **A run is one command:** `uv run python scripts/supervise.py --run-id <id>
  --population <112|102|47>`. It resumes after any interruption and is a no-op
  once complete.
