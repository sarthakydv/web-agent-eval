"""Episodes that behave badly on purpose, so `feat-004` can be tested offline.

`feat-004`'s subject is what the batch does *around* an episode — resume,
retries, provider errors, caps, budgets, killed workers — and none of that needs
a browser or a model to be exercised. It needs episodes that fail in specific
ways on demand, which is what this module is.

The behaviour is encoded in the task id's **site**, because a worker is a fresh
spawned process and the id is the only thing it is given:

    v1.pass-1     an episode that completes with reward 1
    v1.fail-1     completes with reward 0
    v1.quota-1    errors the way z.ai does when it refuses (entry 4's own text)
    v1.boom-1     errors the way the *agent* does — must NOT read as a provider error
    v1.wedge-1    hits the wall-clock cap and leaves a live thread behind
    v1.capsteps-1 hits the step cap
    v1.flaky-1    refuses on the first attempt, completes on the second
    v1.die-1      exits without reporting at all, as a SIGKILL would
    v1.slow-1     completes, slowly, and logs when it held its site
    v1.fat-1      completes, expensively

Two tasks with the same behaviour share a site (`v1.slow-1`, `v1.slow-2`), which
is exactly what the no-two-episodes-per-site rule is about.
"""

from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path

#: How long `slow` takes. Small by default; the tests that care set it.
SLOW_S = float(os.environ.get("WAE_FAKE_SLOW_S", "1.0"))
#: What `fat` charges, for budget tests.
FAT_TOKENS = int(os.environ.get("WAE_FAKE_FAT_TOKENS", "50000"))
#: Where site-occupancy windows are logged, when a test wants them.
LOG = os.environ.get("WAE_FAKE_LOG")


def _behaviour(task_id: str) -> str:
    name = task_id.split(".", 1)[1] if "." in task_id else task_id
    return name.rsplit("-", 1)[0]


def _attempt(output_path) -> int:
    match = re.search(r"attempt(\d+)", Path(output_path).name)
    return int(match.group(1)) if match else 1


def _log_window(task_id: str, started: float) -> None:
    if not LOG:
        return
    site = _behaviour(task_id)
    with open(LOG, "a") as handle:
        handle.write(f"{task_id}\t{site}\t{started:.4f}\t{time.time():.4f}\n")


def _completed(reward: float, *, steps: int = 3, tokens: int = 1000, elapsed: float = 0.1) -> dict:
    return {
        "task_id": "",
        "outcome": "completed",
        "reward": reward,
        "steps": steps,
        "model_calls": steps,
        "elapsed_s": elapsed,
        "tokens": {"charged": tokens, "provider_tokens": tokens, "local_tokens": 0},
        "level_name": "lean",
        "env_terminated": True,
        "cleanup": {"env_closed": True},
    }


def _errored(error_type: str, message: str) -> dict:
    return {
        "outcome": "errored",
        "reward": None,
        "steps": 0,
        "elapsed_s": 0.1,
        "tokens": {"charged": 0},
        "error": {"type": error_type, "message": message, "traceback": ""},
        "cleanup": {"env_closed": True},
    }


def _capped(cap: str, limit: float, observed: float, unit: str) -> dict:
    return {
        "outcome": "capped",
        "reward": 0.0,
        "steps": 2,
        "elapsed_s": observed if unit == "seconds" else 0.2,
        "tokens": {"charged": 500},
        "cap": {"cap": cap, "limit": limit, "observed": observed, "unit": unit},
        "cleanup": {"env_closed": False, "wedged_on": "env.step"},
    }


def episode(task_id: str, *, caps=None, output_path=None, level: str = "lean") -> dict:
    """One fake episode. Same contract as `batch.real_episode`."""
    started = time.time()
    behaviour = _behaviour(task_id)

    if behaviour == "die":
        # No record, no row, no report — what a SIGKILL leaves behind.
        os._exit(9)

    if behaviour == "slow":
        time.sleep(SLOW_S)
        _log_window(task_id, started)
        return _completed(1.0, elapsed=SLOW_S)

    if behaviour == "hang":
        # Never returns on its own; the parent's hard timeout must end it.
        time.sleep(3600)

    _log_window(task_id, started)

    if behaviour == "pass":
        return _completed(1.0)
    if behaviour == "fail":
        return _completed(0.0)
    if behaviour == "fat":
        return _completed(1.0, tokens=FAT_TOKENS)
    if behaviour == "capsteps":
        return _capped("steps", 25, 25, "steps")
    if behaviour == "wedge":
        # The dangerous case, reproduced exactly: the wall-clock cap fired and
        # the worker thread it was waiting on is still running. Python cannot
        # kill it, and a non-daemon thread keeps the whole process alive at
        # exit — so if the parent does not SIGKILL this process, the round hangs
        # here for an hour.
        threading.Thread(target=time.sleep, args=(3600,), daemon=False).start()
        return _capped("wall_clock", 300.0, 300.4, "seconds")
    if behaviour == "quota":
        return _errored(
            "RateLimitError",
            "Error code: 429 - {'error': {'code': '1113', 'message': "
            "'Insufficient balance or no resource package. Please recharge.'}}",
        )
    if behaviour == "boom":
        # An agent-side failure. If this ever classifies as a provider error it
        # would be retried forever and never counted.
        return _errored(
            "PolicyProducedNoAction",
            "policy returned no action at step 1; raw reply: 'I am not sure what to do'",
        )
    if behaviour == "flaky":
        if _attempt(output_path) == 1:
            return _errored(
                "APIConnectionError", "Connection error (z.ai reset the connection)"
            )
        return _completed(1.0)

    raise ValueError(f"unknown fake behaviour {behaviour!r} in {task_id!r}")
