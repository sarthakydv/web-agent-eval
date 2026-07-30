"""The episode loop: observe, decide, act, repeat, terminate.

One task, one episode, one record. The loop resets an environment, hands each
observation to a policy, feeds the policy's action back to the environment, and
stops on exactly one of three things:

  completed  the environment said so — the agent finished, or the environment
             truncated the episode itself
  capped     one of the three caps fired; the record names which, at what limit,
             on what observed value
  errored    something in the episode broke

**Every episode ends with one of those three recorded, always.** An episode
that ended with no recorded reason is a hole in `feat-004`'s accounting, so the
outcome is set before the loop starts and is never left to a code path that
might not run. Nothing raises out of `run_episode` — a caller running 102 tasks
unattended must get a record back for every one of them.

`completed` is not `passed`. Whether the reward means the task was done is
`feat-004`'s and `feat-005`'s question; entry 7 fixes the terminal statuses at
`passed`, `failed`, `capped` and `errored`, and this loop supplies the two it
can honestly decide plus the reward for the other two.

**Concurrency.** This loop is safe for three copies in three separate processes
(entry 7: z.ai publishes a concurrency limit of 3 for `glm-4.6`). There is no
module-level mutable state and no cached singleton here. The policy, the
environment, the deadline, the token ledger and the worker thread are all built
per episode by factories the caller supplies; nothing is written to a fixed path
— the output path comes from the caller or nothing is written at all; and every
log line carries the task id so interleaved output stays readable.

Scope: this module runs one episode. Batching, retries, the frozen manifest and
the supervisor are `feat-004` (entry 7). Scoring is `feat-005`.
"""

from __future__ import annotations

import json
import logging
import time
import traceback
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from web_agent_eval.caps import (
    BoundedRunner,
    CapHit,
    Caps,
    Deadline,
    TokenLedger,
    Usage,
    WallClockExceeded,
    check,
)

COMPLETED = "completed"
CAPPED = "capped"
ERRORED = "errored"

_LOGGER = logging.getLogger("web_agent_eval.episode")


# --------------------------------------------------------------------------
# what the loop talks to
# --------------------------------------------------------------------------


@runtime_checkable
class Environment(Protocol):
    """A gym-shaped environment. `environment.AgisdkEnvironment` is the real one."""

    def reset(self) -> dict:
        ...

    def step(self, action: str) -> tuple[dict, float, bool, bool, dict]:
        ...

    def close(self) -> None:
        ...


@dataclass(frozen=True)
class Decision:
    """One model call's output: the action to take, and what the call cost."""

    action: str
    raw: str = ""
    usage: Usage | None = None
    #: tokens the serialized observation spent, for the record. See feat-002.
    observation_tokens: int | None = None
    #: section -> lines the serializer dropped to fit its own budget.
    observation_truncated: dict = field(default_factory=dict)


@runtime_checkable
class Policy(Protocol):
    """Observation in, action out. `policy.GlmPolicy` is the real one.

    `level_name` is the observation richness this policy was built with.
    `feat-007` varies it; the loop only records it, because a loop that chose
    the richness would be a second thing varying in that ablation.
    """

    level_name: str

    def propose(
        self,
        observation: dict,
        history: tuple[str, ...],
        timeout_s: float | None = None,
    ) -> Decision:
        ...


class PolicyProducedNoAction(RuntimeError):
    """The policy returned an empty action. Recorded as an error, not papered over."""


# --------------------------------------------------------------------------
# the record
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class StepRecord:
    step: int
    action: str
    executed: bool
    url: str | None = None
    reward: float | None = None
    terminated: bool = False
    truncated: bool = False
    last_action_error: str | None = None
    usage: dict | None = None
    observation_tokens: int | None = None
    observation_truncated: dict = field(default_factory=dict)
    elapsed_s: float = 0.0
    raw: str = ""


@dataclass(frozen=True)
class EpisodeRecord:
    """Everything one episode is allowed to claim about itself."""

    task_id: str
    outcome: str
    caps: dict
    steps: int
    model_calls: int
    elapsed_s: float
    tokens: dict
    level_name: str | None = None
    cap: dict | None = None
    reward: float | None = None
    env_terminated: bool = False
    env_truncated: bool = False
    error: dict | None = None
    cleanup: dict = field(default_factory=dict)
    trace: list = field(default_factory=list)
    output_path: str | None = None
    output_error: str | None = None

    @property
    def capped(self) -> bool:
        return self.outcome == CAPPED

    def termination(self) -> dict:
        """The machine-readable reason, in the shape `feat-004` records.

        Always populated. `{"outcome": "capped", "cap": "wall_clock",
        "limit": 300.0, "observed": 300.4, "unit": "seconds"}` is a different
        statement from "the agent failed the task", and entry 7 publishes it
        separately for exactly that reason.
        """
        reason: dict[str, Any] = {"outcome": self.outcome}
        if self.cap:
            reason.update(self.cap)
        if self.error:
            reason["error"] = self.error.get("type")
        return reason

    def to_dict(self) -> dict:
        data = asdict(self)
        data["termination"] = self.termination()
        return data

    def describe(self) -> str:
        bits = [f"{self.task_id}: {self.outcome}"]
        if self.cap:
            bits.append(f"on the {self.cap['cap']} cap ({self.cap['observed']:g}"
                        f"/{self.cap['limit']:g} {self.cap['unit']})")
        bits.append(f"{self.steps} steps, {self.tokens['charged']} tokens, "
                    f"{self.elapsed_s:.1f}s")
        return " ".join(bits)


class _TaskLog(logging.LoggerAdapter):
    """Every line carries the task id — three interleaved episodes stay readable."""

    def process(self, msg, kwargs):
        return f"[{self.extra['task_id']}] {msg}", kwargs


# --------------------------------------------------------------------------
# the loop
# --------------------------------------------------------------------------


def run_episode(
    task_id: str,
    *,
    env_factory: Callable[[], Environment],
    policy_factory: Callable[[], Policy],
    caps: Caps | None = None,
    output_path: str | Path | None = None,
    clock: Callable[[], float] = time.monotonic,
    logger: logging.Logger | None = None,
) -> EpisodeRecord:
    """Run one episode of `task_id` under `caps`. Never raises; always records why.

    `env_factory` and `policy_factory` are called *inside* the episode, on the
    episode's own worker thread. That is not ceremony: it is what keeps three
    concurrent episodes from sharing a model client or a browser handle, and it
    is what gives Playwright's sync API the single thread it requires.

    `output_path` is the caller's. Nothing here writes to a fixed location, so
    two episodes under `runs/` cannot collide.
    """
    caps = caps or Caps()
    log = _TaskLog(logger or _LOGGER, {"task_id": task_id})
    deadline = Deadline(caps.max_wall_clock_s, clock=clock)
    ledger = TokenLedger()
    runner = BoundedRunner(deadline, task_id=task_id)

    # Set before anything can fail, so no path returns an episode with no reason.
    outcome = ERRORED
    hit: CapHit | None = None
    error: dict | None = None
    trace: list[StepRecord] = []
    steps = 0
    model_calls = 0
    reward: float | None = None
    env_terminated = False
    env_truncated = False
    level_name: str | None = None
    env: Environment | None = None

    log.info("episode start: caps=%s", caps.to_dict())
    try:
        policy = runner.run("policy_factory", policy_factory)
        level_name = getattr(policy, "level_name", None)
        env = runner.run("env_factory", env_factory)
        obs = runner.run("env.reset", env.reset)

        history: list[str] = []
        while True:
            hit = check(caps, deadline, ledger, steps)
            if hit is not None:
                outcome = CAPPED
                break

            step_started = clock()
            decision = runner.run(
                "policy.propose",
                policy.propose,
                obs,
                tuple(history),
                # The per-request timeout is derived FROM the episode budget,
                # never set independently of it. That is the whole inherited
                # lesson: a sub-timeout that does not know the deadline is how
                # nine minutes fits inside a 45 s bound.
                max(deadline.remaining(), 0.0),
            )
            model_calls += 1
            if decision.usage is not None:
                ledger.add(decision.usage)

            # Charged as soon as the call returns, so the cap fires on the call
            # that crossed it rather than a step later.
            hit = check(caps, deadline, ledger, steps)
            if hit is not None:
                outcome = CAPPED
                trace.append(_step_record(
                    steps + 1, decision, executed=False, elapsed_s=clock() - step_started,
                ))
                break

            action = (decision.action or "").strip()
            if not action:
                raise PolicyProducedNoAction(
                    f"policy returned no action at step {steps + 1}; raw reply: {decision.raw[:200]!r}"
                )

            obs, step_reward, env_terminated, env_truncated, _info = runner.run(
                "env.step", env.step, action
            )
            steps += 1
            reward = (reward or 0.0) + float(step_reward or 0.0)
            history.append(action)
            trace.append(_step_record(
                steps,
                decision,
                executed=True,
                elapsed_s=clock() - step_started,
                url=obs.get("url") if isinstance(obs, dict) else None,
                reward=step_reward,
                terminated=env_terminated,
                truncated=env_truncated,
                last_action_error=(obs.get("last_action_error") or None)
                if isinstance(obs, dict) else None,
            ))
            log.info("step %d: %s", steps, action[:120])

            if env_terminated or env_truncated:
                outcome = COMPLETED
                break

    except WallClockExceeded as exc:
        # A hang is a cap, not a crash. The reason is the same whether the
        # deadline was noticed between steps or hit inside one.
        outcome = CAPPED
        hit = exc.hit
        log.warning("wall-clock cap fired inside %s: %s", exc.operation, hit.describe())
    except Exception as exc:  # noqa: BLE001 — nothing escapes to the caller
        outcome = ERRORED
        error = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        log.warning("episode errored: %s: %s", type(exc).__name__, exc)

    cleanup = _close(runner, env, log)

    if outcome == CAPPED and hit is not None:
        log.warning("episode capped: %s", hit.describe())

    record = EpisodeRecord(
        task_id=task_id,
        outcome=outcome,
        caps=caps.to_dict(),
        steps=steps,
        model_calls=model_calls,
        elapsed_s=deadline.elapsed(),
        tokens=ledger.to_dict(),
        level_name=level_name,
        cap=hit.to_dict() if hit is not None else None,
        reward=reward,
        env_terminated=env_terminated,
        env_truncated=env_truncated,
        error=error,
        cleanup=cleanup,
        trace=[asdict(s) for s in trace],
        output_path=str(output_path) if output_path else None,
    )
    record = _write(record, output_path, log)
    log.info("episode end: %s", record.describe())
    return record


def _step_record(step: int, decision: Decision, *, executed: bool, **extra) -> StepRecord:
    return StepRecord(
        step=step,
        action=decision.action,
        executed=executed,
        raw=decision.raw,
        usage=decision.usage.to_dict() if decision.usage else None,
        observation_tokens=decision.observation_tokens,
        observation_truncated=dict(decision.observation_truncated),
        **extra,
    )


def _close(runner: BoundedRunner, env: Environment | None, log: _TaskLog) -> dict:
    """Bounded cleanup. A wedged worker is reported, never waited on."""
    cleanup: dict[str, Any] = {
        "env_closed": False,
        "wedged_on": runner.wedged_on,
        "close_timed_out": False,
    }
    if env is not None and not runner.is_wedged:
        try:
            runner.run_for_cleanup("env.close", env.close)
            cleanup["env_closed"] = True
        except WallClockExceeded:
            cleanup["close_timed_out"] = True
            log.warning("env.close did not return within the cleanup grace")
        except Exception as exc:  # noqa: BLE001
            cleanup["close_error"] = f"{type(exc).__name__}: {exc}"
            log.warning("env.close raised: %s", exc)
    elif runner.is_wedged:
        # Nothing can be sent to a thread that never came back. entry 7 puts
        # each episode in its own process for exactly this: process exit is
        # what reclaims the browser.
        log.warning("worker wedged on %s; leaving cleanup to process exit", runner.wedged_on)
    runner.close()
    return cleanup


def _write(record: EpisodeRecord, output_path: str | Path | None, log: _TaskLog) -> EpisodeRecord:
    if not output_path:
        return record
    try:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record.to_dict(), indent=2, default=str))
    except Exception as exc:  # noqa: BLE001 — a bad path is not a lost episode
        log.error("could not write the episode record to %s: %s", output_path, exc)
        return replace(record, output_error=f"{type(exc).__name__}: {exc}")
    return record
