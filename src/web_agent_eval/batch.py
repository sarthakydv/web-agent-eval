"""The batch runner: one round of the manifest, in worker processes, with resume.

One round attempts every manifest task that has no terminal record yet, and
returns. The supervisor (`scripts/supervise.py`) decides whether another round
is warranted; this module never loops until something passes.

**Resume is the whole point.** The archived predecessor lost an eight-hour run
that produced nothing because it could not resume after a failure (AGENTS.md,
lesson 2). Here, a task with a terminal record is never attempted again, and
every round says how many it skipped. One task's failure never aborts the batch.

**Workers are processes, not threads** (docs/DECISIONS.md entry 7). agisdk
drives Playwright's *sync* API, which has thread affinity, and a process
boundary contains a browser crash or a leak to one episode.

**A process that hit the wall-clock cap is retired, never reused.**
`feat-003`'s cap is enforced with `future.result(timeout=...)` on a worker
thread, and Python cannot kill a thread. When the cap fires, that thread is
*abandoned, not terminated* — it may still be driving a browser. Handing the
same process another task would let the abandoned thread touch the next task's
environment, and REAL scores by **diffing environment state**, so the next
task's diff would be contaminated and its score silently wrong. That is exactly
the class of error entry 7 exists to prevent, so the process is killed and a
fresh one starts. One process per task makes reuse structurally impossible, and
the kill makes the abandoned thread stop. **The task's site stays reserved until
that process is confirmed dead**, for the same reason.

**No two concurrent episodes on the same site** (entry 7), for the same
state-diff reason, until isolation is measured.
"""

from __future__ import annotations

import importlib
import json
import multiprocessing as mp
import os
import queue as queue_module
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from web_agent_eval import records
from web_agent_eval.caps import Caps
from web_agent_eval.manifest import Manifest, site_of

#: How many clean completions it takes to win back one worker after a provider
#: error halved the level. Entry 7: halve on one, "recover slowly".
RECOVER_AFTER_CLEAN = 5

#: Grace for a worker process to exit on its own after it has reported. Short:
#: everything it had to record is already on disk before it reports.
EXIT_GRACE_S = 10.0

#: A worker that has reported a wall-clock cap gets almost none of that grace —
#: the abandoned thread is the reason to kill it, and waiting is what lets it
#: keep driving a browser.
WEDGED_EXIT_GRACE_S = 1.0

#: How long past its own wall-clock cap a worker may go before the parent gives
#: up on hearing from it at all. Covers process start and the cleanup grace.
HARD_TIMEOUT_MARGIN_S = 90.0

BUDGET_EXIT_CODE = 2


# --------------------------------------------------------------------------
# the episode entrypoint
# --------------------------------------------------------------------------


def resolve_entrypoint(spec: str) -> Callable[..., Any]:
    """`module:function` -> the function. Resolved in the worker, not the parent."""
    module_name, _, attribute = spec.partition(":")
    if not attribute:
        raise ValueError(f"entrypoint must look like 'module:function', got {spec!r}")
    return getattr(importlib.import_module(module_name), attribute)


def real_episode(task_id: str, *, caps: Caps, output_path: Path, level: str = "lean") -> dict:
    """The real thing: one REAL task, driven by GLM, under `feat-003`'s caps.

    Imported inside the function so the parent process never pulls in agisdk,
    Playwright or the model client — only the workers do.

    **The judge is instrumented before the episode starts** (`feat-005`,
    DECISIONS entry 10). agisdk grades `llm_boolean` evals with its own OpenAI
    judge, and two things have to be recorded rather than assumed: that the
    judge was actually called, and that it was called against OpenAI rather
    than against whatever `OPENAI_BASE_URL` happened to hold. A task that needs
    the judge refuses to run if either is wrong, because a misrouted judge
    produces a score that looks exactly like a good one.
    """
    from web_agent_eval import judge
    from web_agent_eval.environment import agisdk_env_factory
    from web_agent_eval.episode import run_episode
    from web_agent_eval.policy import glm_policy_factory

    judge.reset()
    needs_judge = judge.task_needs_judge(task_id)
    endpoint_info = judge.require() if needs_judge else judge.endpoint()
    judge.install(endpoint_info=endpoint_info)

    record = run_episode(
        task_id,
        env_factory=agisdk_env_factory(task_id),
        policy_factory=glm_policy_factory(level),
        caps=caps,
        output_path=output_path,
    )
    data = record.to_dict()
    data["needs_judge"] = needs_judge
    data["judge"] = judge.ledger().to_dict()
    return data


# --------------------------------------------------------------------------
# the worker process
# --------------------------------------------------------------------------


def _worker(
    task_id: str,
    run_dir: str,
    caps_dict: dict,
    entrypoint: str,
    level: str,
    round_index: int,
    result_queue,
) -> None:
    """One task, in its own process. Writes its own attempt row and record.

    The worker writes both, in this order, before it reports back:
      1. the attempt row in `results.tsv`  (append-only, one row per attempt)
      2. the terminal record, atomically   (only if the status is terminal)
    A kill between the two leaves an attempt visible and the task still pending,
    which resumes correctly. The reverse order could not.
    """
    started = time.monotonic()
    attempt = records.attempt_number(run_dir, task_id)
    episode_path = records.episodes_dir(run_dir) / f"{task_id}.attempt{attempt}.json"
    episode_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        record = resolve_entrypoint(entrypoint)(
            task_id, caps=Caps(**caps_dict), output_path=episode_path, level=level
        )
        if hasattr(record, "to_dict"):
            record = record.to_dict()
    except BaseException as exc:  # noqa: BLE001 — the worker must still report
        import traceback
        record = {
            "outcome": "errored",
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
            "steps": 0,
            "elapsed_s": time.monotonic() - started,
            "tokens": {"charged": 0},
        }

    status = records.classify(record)
    cap = (record.get("cap") or {}).get("cap")
    payload = {
        "task_id": task_id,
        "site": site_of(task_id),
        "status": status,
        "attempt": attempt,
        "round": round_index,
        "recorded": datetime.now(UTC).isoformat(timespec="seconds"),
        "reward": record.get("reward"),
        "steps": record.get("steps"),
        "tokens": (record.get("tokens") or {}).get("charged"),
        "wall_clock_s": record.get("elapsed_s"),
        "cap": cap,
        "cap_detail": record.get("cap"),
        "outcome": record.get("outcome"),
        "error": record.get("error"),
        "cleanup": record.get("cleanup"),
        "level_name": record.get("level_name"),
        # feat-005: the judge's own accounting travels in the terminal record,
        # because the terminal records are the only thing the aggregation is
        # allowed to read (see `scoring.py`).
        "needs_judge": record.get("needs_judge"),
        "judge": record.get("judge"),
        "episode_path": str(episode_path),
    }

    run_id = Path(run_dir).name
    records.append_attempt(run_dir, records.Attempt(
        run_id=run_id,
        round=round_index,
        attempt=attempt,
        task_id=task_id,
        site=payload["site"],
        status=status,
        reward=payload["reward"],
        steps=payload["steps"],
        tokens=payload["tokens"],
        wall_clock_s=payload["wall_clock_s"],
        cap=cap,
        error_type=(record.get("error") or {}).get("type"),
        note=(record.get("error") or {}).get("message", "")[:120],
    ))
    if records.is_terminal(status):
        records.write_terminal_record(run_dir, task_id, payload)

    result_queue.put(payload)


# --------------------------------------------------------------------------
# the round
# --------------------------------------------------------------------------


@dataclass
class Budget:
    """The run-level bounds the supervisor exits 2 on. `None` means unbounded."""

    tokens: int | None = None
    wall_clock_s: float | None = None

    def exceeded(self, *, tokens: int, elapsed_s: float) -> str | None:
        if self.tokens is not None and tokens >= self.tokens:
            return f"token budget exceeded: {tokens} >= {self.tokens}"
        if self.wall_clock_s is not None and elapsed_s >= self.wall_clock_s:
            return f"wall-clock budget exceeded: {elapsed_s:.1f}s >= {self.wall_clock_s:.1f}s"
        return None


@dataclass
class RoundResult:
    round: int
    skipped: int
    pending_at_start: int
    attempted: list[str] = field(default_factory=list)
    new_terminal: list[str] = field(default_factory=list)
    statuses: dict = field(default_factory=dict)
    provider_errors: int = 0
    retired: list[dict] = field(default_factory=list)
    budget_stop: str | None = None
    concurrency_start: int = 0
    concurrency_end: int = 0
    tokens_after: int = 0
    elapsed_s: float = 0.0
    #: What entry 7's "no two concurrent episodes on the same site" rule cost.
    #: The pilot's ten tasks — one per site — never reached it, so until this
    #: run the rule had never been exercised and its price was unmeasured.
    #: `reorders` counts the launches that had to pass over a queued task whose
    #: site was busy; `blocked_events` counts the moments a free worker slot
    #: could not be filled at all; `idle_slot_s` is what that cost, in
    #: worker-seconds a slot sat empty with work still queued.
    site_reorders: int = 0
    site_tasks_passed_over: int = 0
    site_blocked_events: int = 0
    site_idle_slot_s: float = 0.0
    slot_s_available: float = 0.0

    def to_dict(self) -> dict:
        return {
            "round": self.round,
            "skipped_already_terminal": self.skipped,
            "pending_at_start": self.pending_at_start,
            "attempted": self.attempted,
            "new_terminal": self.new_terminal,
            "statuses": self.statuses,
            "provider_errors": self.provider_errors,
            "retired_processes": self.retired,
            "budget_stop": self.budget_stop,
            "concurrency_start": self.concurrency_start,
            "concurrency_end": self.concurrency_end,
            "tokens_after": self.tokens_after,
            "elapsed_s": round(self.elapsed_s, 2),
            "site_constraint": {
                "reorders": self.site_reorders,
                "tasks_passed_over": self.site_tasks_passed_over,
                "blocked_events": self.site_blocked_events,
                "idle_slot_s": round(self.site_idle_slot_s, 2),
                "slot_s_available": round(self.slot_s_available, 2),
                "idle_fraction": (
                    round(self.site_idle_slot_s / self.slot_s_available, 5)
                    if self.slot_s_available else None
                ),
            },
        }


class _Flight:
    """One live worker: its process, its task, and when it was launched."""

    __slots__ = ("payload", "proc", "site", "started", "task_id")

    def __init__(self, task_id: str, site: str, proc, started: float) -> None:
        self.task_id = task_id
        self.site = site
        self.proc = proc
        self.started = started
        self.payload: dict | None = None


def run_round(
    run_dir: Path | str,
    manifest: Manifest,
    *,
    round_index: int = 1,
    concurrency: int | None = None,
    budget: Budget | None = None,
    run_started: float | None = None,
    level: str = "lean",
    log: Callable[[str], None] = print,
) -> RoundResult:
    """Attempt every task with no terminal record. Returns what happened."""
    run_dir = Path(run_dir)
    budget = budget or Budget()
    caps = Caps(**manifest.caps)
    configured = concurrency or manifest.concurrency
    effective = configured
    clean_streak = 0
    started_at = time.monotonic()
    run_started = run_started if run_started is not None else started_at

    done = records.terminal_task_ids(run_dir)
    pending = [t for t in manifest.task_ids if t not in done]
    result = RoundResult(
        round=round_index,
        skipped=len(manifest.task_ids) - len(pending),
        pending_at_start=len(pending),
        concurrency_start=effective,
    )
    # Stated every round, not only on the first: "how many it skipped" is the
    # sentence that says resume worked.
    log(f"round {round_index}: {result.skipped} of {len(manifest.task_ids)} already terminal "
        f"(skipping them), {len(pending)} pending, concurrency {effective}")
    if not pending:
        result.concurrency_end = effective
        result.tokens_after = records.summarise(run_dir, manifest.task_ids)["tokens"]
        return result

    ctx = mp.get_context("spawn")
    result_queue = ctx.Queue()
    in_flight: list[_Flight] = []
    queued = list(pending)
    hard_timeout = caps.max_wall_clock_s + HARD_TIMEOUT_MARGIN_S

    def tokens_spent() -> int:
        return records.tokens_spent(run_dir)

    def busy_sites() -> set[str]:
        return {f.site for f in in_flight}

    def launch(task_id: str) -> None:
        proc = ctx.Process(
            target=_worker,
            args=(task_id, str(run_dir), manifest.caps, manifest.episode_entrypoint,
                  level, round_index, result_queue),
            name=f"episode-{task_id}",
            daemon=False,
        )
        proc.start()
        in_flight.append(_Flight(task_id, site_of(task_id), proc, time.monotonic()))
        result.attempted.append(task_id)
        log(f"  launch {task_id} (pid {proc.pid}, site {site_of(task_id)}, "
            f"{len(in_flight)}/{effective} in flight)")

    def retire(flight: _Flight, *, reason: str, wedged: bool) -> None:
        """Stop the worker for good. A wedged one is killed, not waited on."""
        grace = WEDGED_EXIT_GRACE_S if wedged else EXIT_GRACE_S
        flight.proc.join(grace)
        killed = False
        if flight.proc.is_alive():
            flight.proc.kill()
            flight.proc.join(5)
            killed = True
        if killed or wedged:
            note = {
                "task_id": flight.task_id,
                "pid": flight.proc.pid,
                "reason": reason,
                "killed": killed,
            }
            result.retired.append(note)
            log(f"  retired {flight.task_id} (pid {flight.proc.pid}): {reason}"
                f"{' — SIGKILLed' if killed else ''}")
        # The site is freed only now. An abandoned thread inside a wedged worker
        # can still be driving that site's browser, and a second episode on the
        # same site would have its state diff contaminated by it.
        in_flight.remove(flight)

    def handle(payload: dict) -> None:
        task_id = payload["task_id"]
        status = payload["status"]
        result.statuses[status] = result.statuses.get(status, 0) + 1
        if records.is_terminal(status):
            result.new_terminal.append(task_id)
        detail = f"reward={payload.get('reward')} steps={payload.get('steps')} " \
                 f"tokens={payload.get('tokens')} {payload.get('wall_clock_s') or 0:.1f}s"
        if payload.get("cap"):
            detail += f" cap={payload['cap']}"
        log(f"  {task_id}: {status} ({detail})")

        nonlocal effective, clean_streak
        if status == records.PROVIDER_ERROR:
            result.provider_errors += 1
            clean_streak = 0
            if effective > 1:
                effective = max(1, effective // 2)
                log(f"  provider error -> halving concurrency to {effective} "
                    f"(DECISIONS entry 7)")
        else:
            clean_streak += 1
            if clean_streak >= RECOVER_AFTER_CLEAN and effective < configured:
                effective += 1
                clean_streak = 0
                log(f"  {RECOVER_AFTER_CLEAN} clean episodes -> concurrency back up "
                    f"to {effective}")

    def collect(flight: _Flight, payload: dict) -> None:
        flight.payload = payload
        handle(payload)
        wedged = payload.get("cap") == "wall_clock"
        reason = (
            "wall-clock cap fired: the episode's worker thread was abandoned, not "
            "terminated, so this process must not run another task"
            if wedged else "episode finished"
        )
        retire(flight, reason=reason, wedged=wedged)

    def abort_all(note: str) -> None:
        # Anything already reported is already recorded; take it before killing,
        # so a worker that finished in the same instant is not filed as aborted.
        while True:
            try:
                payload = result_queue.get_nowait()
            except (queue_module.Empty, OSError, ValueError):
                break
            flight = next((f for f in in_flight if f.task_id == payload["task_id"]), None)
            if flight is not None:
                collect(flight, payload)
        for flight in list(in_flight):
            log(f"  aborting {flight.task_id} (pid {flight.proc.pid}): {note}")
            records.append_attempt(run_dir, records.Attempt(
                run_id=manifest.run_id, round=round_index,
                attempt=records.attempt_number(run_dir, flight.task_id),
                task_id=flight.task_id, site=flight.site,
                status=records.ABORTED, note=note,
            ))
            flight.proc.kill()
            flight.proc.join(5)
            in_flight.remove(flight)

    # What the site rule costs, accounted in worker-seconds rather than
    # asserted. `blocked_slots` is how many slots the rule is holding empty as
    # of the last pass; each pass adds that many slot-seconds to the bill.
    last_tick = time.monotonic()
    blocked_slots = 0
    try:
        while queued or in_flight:
            now = time.monotonic()
            elapsed_tick = now - last_tick
            last_tick = now
            result.slot_s_available += effective * elapsed_tick
            if blocked_slots:
                result.site_idle_slot_s += blocked_slots * elapsed_tick

            stop = budget.exceeded(
                tokens=tokens_spent(), elapsed_s=time.monotonic() - run_started
            )
            if stop:
                result.budget_stop = stop
                log(f"  BUDGET: {stop} — stopping mid-run; every terminal record stands")
                abort_all("stopped on the run budget")
                break

            passed_over = 0
            while queued and len(in_flight) < effective:
                busy = busy_sites()
                # The first queued task whose site is free. Its index is how
                # many tasks the rule made this launch step over: the manifest
                # is ordered by site, so with 3 workers on 10 sites this is
                # reached on nearly every launch rather than only at the tail.
                nxt = None
                for index, task_id in enumerate(queued):
                    if site_of(task_id) not in busy:
                        nxt = task_id
                        passed_over += index
                        break
                if nxt is None:
                    break  # everything left is on a site already in flight
                queued.remove(nxt)
                launch(nxt)
            if passed_over:
                result.site_reorders += 1
                result.site_tasks_passed_over += passed_over

            was_blocked = blocked_slots > 0
            blocked_slots = max(0, effective - len(in_flight)) if queued else 0
            if blocked_slots and not was_blocked:
                result.site_blocked_events += 1
                log(f"  site rule: {blocked_slots} slot(s) idle — every one of the "
                    f"{len(queued)} queued tasks is on a site already in flight "
                    f"({sorted(busy_sites())})")

            try:
                payload = result_queue.get(timeout=0.5)
            except queue_module.Empty:
                payload = None
            if payload is not None:
                flight = next((f for f in in_flight if f.task_id == payload["task_id"]), None)
                if flight is not None:
                    collect(flight, payload)
                continue

            now = time.monotonic()
            for flight in list(in_flight):
                if not flight.proc.is_alive():
                    # Exited without reporting: killed, crashed, or SIGKILLed
                    # from outside. Non-terminal — the task stays pending.
                    code = flight.proc.exitcode
                    log(f"  {flight.task_id}: worker died without reporting "
                        f"(exit {code}) — task stays pending")
                    records.append_attempt(run_dir, records.Attempt(
                        run_id=manifest.run_id, round=round_index,
                        attempt=records.attempt_number(run_dir, flight.task_id),
                        task_id=flight.task_id, site=flight.site,
                        status=records.WORKER_DIED,
                        note=f"worker exited {code} without reporting",
                    ))
                    result.statuses[records.WORKER_DIED] = \
                        result.statuses.get(records.WORKER_DIED, 0) + 1
                    in_flight.remove(flight)
                elif now - flight.started > hard_timeout:
                    log(f"  {flight.task_id}: no report {now - flight.started:.0f}s in "
                        f"(cap is {caps.max_wall_clock_s:g}s) — killing the worker")
                    records.append_attempt(run_dir, records.Attempt(
                        run_id=manifest.run_id, round=round_index,
                        attempt=records.attempt_number(run_dir, flight.task_id),
                        task_id=flight.task_id, site=flight.site,
                        status=records.WORKER_DIED,
                        note=f"no report within {hard_timeout:.0f}s of the episode cap",
                    ))
                    result.statuses[records.WORKER_DIED] = \
                        result.statuses.get(records.WORKER_DIED, 0) + 1
                    retire(flight, reason="silent past its cap", wedged=True)
    finally:
        for flight in in_flight:
            flight.proc.kill()
            flight.proc.join(5)
        result_queue.close()

    result.concurrency_end = effective
    result.tokens_after = tokens_spent()
    result.elapsed_s = time.monotonic() - started_at
    return result


def write_round_log(run_dir: Path | str, result: RoundResult) -> Path:
    """One round's own log line, and a file the supervisor can read back."""
    directory = Path(run_dir) / "rounds"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"round_{result.round:03d}.json"
    path.write_text(json.dumps(result.to_dict(), indent=2))
    line = json.dumps({"ts": datetime.now(UTC).isoformat(timespec="seconds"),
                       **result.to_dict()})
    with open(Path(run_dir) / "rounds.jsonl", "a") as handle:
        handle.write(line + "\n")
    return path


def install_kill_on_parent_death() -> None:
    """Best-effort: do not leave orphan browsers if the parent is SIGKILLed.

    A worker whose parent has gone is reparented to init and would keep driving
    a browser forever. There is no portable `PR_SET_PDEATHSIG` on macOS, so
    workers are started in the parent's own process group and the group is what
    a `kill` reaches.
    """
    try:
        os.setpgrp()
    except (AttributeError, PermissionError, OSError):
        pass


def kill_process_group() -> None:
    """Used by the CLI on Ctrl-C: take the workers down with the runner."""
    try:
        os.killpg(os.getpgrp(), signal.SIGKILL)
    except (AttributeError, PermissionError, ProcessLookupError, OSError):
        pass
