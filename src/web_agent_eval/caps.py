"""The three caps, their clocks and their counters. One set per episode.

An episode is bounded three ways — steps, tokens and wall clock — and each bound
is configurable, fires on its own, and says so in machine-readable form when it
does.

**The inherited lesson, and the reason `BoundedRunner` exists.** The archived
predecessor sat on one site for nine minutes with every sub-timeout set to 45 s
or less. Per-operation timeouts do not compose into a bound on the whole
operation, and a cap *checked between steps* is not a wall-clock cap either — a
single step that hangs sails straight past it, because the check never runs.
So the deadline here bounds the step itself: every operation an episode performs
is submitted to that episode's own worker thread and awaited with the time
remaining on the episode deadline. A step cannot outlive the episode's budget,
whatever it is blocked on.

**Concurrency.** Nothing in this module is module-level mutable state and
nothing is cached across episodes. `Deadline`, `TokenLedger` and `BoundedRunner`
are per-episode objects with their own clock, counters and thread. `feat-004`
aggregates across episodes; the loop never does.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any

from web_agent_eval.observation import MEASURED_LOCAL_UNDERCOUNT
from web_agent_eval.tokens import make_encoder

# --------------------------------------------------------------------------
# the caps
# --------------------------------------------------------------------------

STEPS = "steps"
TOKENS = "tokens"
WALL_CLOCK = "wall_clock"

#: Order in which simultaneously-satisfied caps are reported. Two caps can be
#: over their limit on the same check — the token ledger and the step counter
#: both cross on the same step, say — and "whichever the code happened to test
#: first" is not a reason. Wall clock outranks the rest because a passed
#: deadline is the truest statement about why the episode stopped; tokens
#: outrank steps because a token cap is the one that bounds spend.
CAP_PRECEDENCE = (WALL_CLOCK, TOKENS, STEPS)

#: 25 steps. agisdk's own harness default, and the gate's successful episode
#: took 9 (docs/DECISIONS.md entry 4).
DEFAULT_MAX_STEPS = 25

#: 400 000 provider-side tokens. Derived, not guessed: `scripts/cap_budget.py`
#: measures the worst-case step against the committed fixtures and the number
#: above it is rounded up from that. See docs/DECISIONS.md entry 11 — the cap is
#: an input to the tokens-per-task claim (entry 9), not only a safety bound, so
#: it is deliberately set clear of the honest worst case rather than tight to it.
#: A cap that bites on the rich arm and not the lean one would confound
#: `feat-007`, which is the failure this number is chosen to avoid.
DEFAULT_MAX_TOKENS = 400_000

#: 300 s. The gate's episode was 35.4 s over 9 model calls (entry 4); measured
#: round trips to the replica hosts run 0.13–2.37 s. 300 s is roughly 3x the
#: expected worst case and well inside the nine-minute hang this bound exists
#: to make impossible.
DEFAULT_MAX_WALL_CLOCK_S = 300.0

#: How long cleanup gets after the episode is over. Bounded separately from the
#: episode deadline, because a deadline that has already passed would leave no
#: time to close a browser and closing it is worth a few seconds.
DEFAULT_CLEANUP_TIMEOUT_S = 10.0


@dataclass(frozen=True)
class Caps:
    """The three bounds on one episode. Each is enforced independently."""

    max_steps: int = DEFAULT_MAX_STEPS
    max_tokens: int = DEFAULT_MAX_TOKENS
    max_wall_clock_s: float = DEFAULT_MAX_WALL_CLOCK_S

    def __post_init__(self) -> None:
        for field_name in ("max_steps", "max_tokens", "max_wall_clock_s"):
            value = getattr(self, field_name)
            if value <= 0:
                raise ValueError(f"{field_name} must be positive, got {value!r}")

    def to_dict(self) -> dict:
        return {
            "max_steps": self.max_steps,
            "max_tokens": self.max_tokens,
            "max_wall_clock_s": self.max_wall_clock_s,
        }


@dataclass(frozen=True)
class CapHit:
    """Which cap ended the episode, at what limit, on what observed value.

    This is the machine-readable reason `feat-004` records beside a `capped`
    result. "The episode was capped" is not enough to publish "k of n tasks
    ended on a cap, and here is which cap".
    """

    cap: str
    limit: float
    observed: float
    unit: str

    def describe(self) -> str:
        return f"{self.cap} cap: {self.observed:g} {self.unit} against a limit of {self.limit:g}"

    def to_dict(self) -> dict:
        return {
            "cap": self.cap,
            "limit": self.limit,
            "observed": self.observed,
            "unit": self.unit,
        }


class WallClockExceeded(Exception):
    """Raised inside the loop when an operation outran the episode deadline.

    Carries the `CapHit` so the caller records the same reason whether the
    deadline was noticed between steps or hit inside one.
    """

    def __init__(self, hit: CapHit, operation: str) -> None:
        super().__init__(f"{operation}: {hit.describe()}")
        self.hit = hit
        self.operation = operation


# --------------------------------------------------------------------------
# the clock
# --------------------------------------------------------------------------


class Deadline:
    """One episode's wall clock. Monotonic, owned by that episode, injectable."""

    def __init__(self, limit_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._limit = float(limit_s)
        self._clock = clock
        self._start = clock()

    @property
    def limit(self) -> float:
        return self._limit

    def elapsed(self) -> float:
        return self._clock() - self._start

    def remaining(self) -> float:
        return self._limit - self.elapsed()

    def expired(self) -> bool:
        return self.remaining() <= 0

    def hit(self) -> CapHit:
        return CapHit(cap=WALL_CLOCK, limit=self._limit, observed=self.elapsed(), unit="seconds")


# --------------------------------------------------------------------------
# the token ledger
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Usage:
    """One model call's token cost, and where the number came from.

    `source` is `"provider"` when z.ai's own `usage` field was available and
    `"local"` when it had to be reconstructed with `tiktoken`. The two are not
    the same number and the record keeps them apart — docs/DECISIONS.md entry 6
    measured `cl100k_base` understating z.ai's `prompt_tokens` by 1.5% in
    aggregate and 2.2% at worst.
    """

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    source: str = "provider"

    def to_dict(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "source": self.source,
        }


class TokenLedger:
    """Per-episode token accounting, in provider-side units.

    **The cap is enforced on the provider's numbers where they exist.** Every
    z.ai chat completion returns `usage`, so in normal operation every token
    charged here is a token z.ai counted (entry 4). When a response arrives
    without `usage`, the cost is reconstructed locally with `tiktoken` and
    marked up by `MEASURED_LOCAL_UNDERCOUNT` — the 2.2% worst case entry 6
    measured — so the fallback errs toward charging *more* than the provider
    would. A cap enforced on an uncorrected local count is looser than it reads,
    and this is where that correction is applied rather than assumed away.
    """

    def __init__(
        self,
        *,
        undercount: float = MEASURED_LOCAL_UNDERCOUNT,
        encoding: str | None = None,
    ) -> None:
        # Built per episode: an episode's counter is never shared with another's.
        self._encoder = make_encoder(encoding)
        self._undercount = undercount
        self.charged = 0
        self.provider_tokens = 0
        self.local_tokens = 0
        self.provider_calls = 0
        self.local_calls = 0

    def count_text(self, text: str) -> int:
        return len(self._encoder.encode(text, disallowed_special=()))

    def local_usage(self, prompt: str, completion: str) -> Usage:
        """Reconstruct a usage record from the text, when the provider sent none."""
        prompt_tokens = self.count_text(prompt)
        completion_tokens = self.count_text(completion)
        return Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            source="local",
        )

    def add(self, usage: Usage) -> int:
        """Charge one model call. Returns what it cost in provider-side units."""
        if usage.source == "provider":
            cost = usage.total_tokens
            self.provider_tokens += usage.total_tokens
            self.provider_calls += 1
        else:
            cost = math.ceil(usage.total_tokens * self._undercount)
            self.local_tokens += usage.total_tokens
            self.local_calls += 1
        self.charged += cost
        return cost

    def to_dict(self) -> dict:
        return {
            # What the cap is enforced on, in provider-side units.
            "charged": self.charged,
            "provider_tokens": self.provider_tokens,
            "provider_calls": self.provider_calls,
            "local_tokens": self.local_tokens,
            "local_calls": self.local_calls,
            "local_undercount_applied": self._undercount,
            "enforced_on": "provider usage where available, local count x undercount otherwise",
        }


# --------------------------------------------------------------------------
# checking
# --------------------------------------------------------------------------


def check(caps: Caps, deadline: Deadline, ledger: TokenLedger, steps: int) -> CapHit | None:
    """The first cap that has been reached, in `CAP_PRECEDENCE` order, or None."""
    candidates: dict[str, CapHit] = {}
    if deadline.expired():
        candidates[WALL_CLOCK] = deadline.hit()
    if ledger.charged >= caps.max_tokens:
        candidates[TOKENS] = CapHit(
            cap=TOKENS, limit=caps.max_tokens, observed=ledger.charged, unit="tokens"
        )
    if steps >= caps.max_steps:
        candidates[STEPS] = CapHit(
            cap=STEPS, limit=caps.max_steps, observed=steps, unit="steps"
        )
    for name in CAP_PRECEDENCE:
        if name in candidates:
            return candidates[name]
    return None


# --------------------------------------------------------------------------
# bounding the step itself
# --------------------------------------------------------------------------


class BoundedRunner:
    """Runs one episode's operations on one worker thread, bounded by its deadline.

    Two properties, both deliberate:

    **One thread, always the same one.** agisdk drives Playwright's *sync* API,
    which has thread affinity: the browser must be built and driven from a
    single thread. So the environment is constructed on this worker and every
    later `reset`/`step`/`close` goes to the same worker. A pool of one is not
    an oversight.

    **The caller waits with a timeout; the worker does not.** `future.result()`
    returns control after `remaining` seconds whatever the worker is doing, so a
    hanging model call or a hanging browser action costs the episode its
    deadline and not a minute more. Python cannot kill the thread it left
    behind, so the runner refuses to submit anything else once one operation has
    outrun its bound and reports the wedged operation in the episode record.
    `feat-004`'s workers are separate *processes* (entry 7) precisely so that a
    wedged browser is reclaimed by process exit rather than accumulated.
    """

    def __init__(
        self,
        deadline: Deadline,
        *,
        task_id: str,
        cleanup_timeout_s: float = DEFAULT_CLEANUP_TIMEOUT_S,
    ) -> None:
        self._deadline = deadline
        self._cleanup_timeout_s = cleanup_timeout_s
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"episode-{task_id}")
        self.wedged_on: str | None = None

    @property
    def is_wedged(self) -> bool:
        return self.wedged_on is not None

    def run(self, operation: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Run `fn` bounded by the time left on the episode deadline."""
        return self._submit(operation, self._deadline.remaining(), fn, args, kwargs)

    def run_for_cleanup(self, operation: str, fn: Callable[..., Any], *args: Any) -> Any:
        """Run `fn` bounded by the cleanup grace, independent of the deadline.

        Closing a browser after the deadline has already passed still has to be
        bounded — it is just not bounded by a budget that is already spent.
        """
        return self._submit(operation, self._cleanup_timeout_s, fn, args, {})

    def _submit(
        self,
        operation: str,
        timeout_s: float,
        fn: Callable[..., Any],
        args: tuple,
        kwargs: dict,
    ) -> Any:
        if self.is_wedged:
            raise WallClockExceeded(self._deadline.hit(), f"{operation} (after {self.wedged_on})")
        if timeout_s <= 0:
            raise WallClockExceeded(self._deadline.hit(), operation)
        future = self._pool.submit(fn, *args, **kwargs)
        try:
            return future.result(timeout=timeout_s)
        except FutureTimeout:
            future.cancel()
            self.wedged_on = operation
            raise WallClockExceeded(self._deadline.hit(), operation) from None

    def close(self) -> None:
        """Release the worker. Never waits — a wedged worker would never return."""
        self._pool.shutdown(wait=False, cancel_futures=True)
