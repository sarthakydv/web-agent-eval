"""feat-003's verification: the three caps, each firing in isolation, cleanly.

`uv run pytest -q -k caps` is the command that decides this feature. Everything
here runs against fakes — no browser, no network, no model call. That is not a
shortcut: the subject under test is the caps, and a real episode would make the
wall-clock case take minutes and be flaky besides. The fakes are deliberately
crude in every dimension except the one being bounded.

**The wall-clock case asserts on elapsed time, not on the return value.** A test
that only checks the returned reason passes even if the loop hung for nine
minutes first, which is exactly the failure the archived predecessor shipped.
The slow step is faked so the assertion is on the bound, not on a real hang.

**Every cap has a control.** Three caps that always fire look identical to three
that work, so each one is also asserted *not* to fire when it should not.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from web_agent_eval.caps import (
    STEPS,
    TOKENS,
    WALL_CLOCK,
    CapHit,
    Caps,
    Deadline,
    TokenLedger,
    Usage,
    check,
)
from web_agent_eval.episode import CAPPED, COMPLETED, ERRORED, Decision, run_episode

# Big enough that the cap under test is the only one in play. Every test below
# sets exactly one of the three tight and leaves the other two here.
LOOSE = {"max_steps": 1000, "max_tokens": 10**9, "max_wall_clock_s": 600.0}


# --------------------------------------------------------------------------
# fakes
# --------------------------------------------------------------------------


class FakeEnv:
    """A gym-shaped environment that counts its calls and can be made to hang."""

    def __init__(self, *, finish_after: int | None = None, step_delay: float = 0.0,
                 reward: float = 1.0, raise_on_step: Exception | None = None) -> None:
        self.finish_after = finish_after
        self.step_delay = step_delay
        self.reward = reward
        self.raise_on_step = raise_on_step
        self.steps = 0
        self.closed = False
        # Lets a test release a "hanging" step once it has made its assertions,
        # so the suite does not sit out the delay it faked.
        self.release = threading.Event()

    def reset(self) -> dict:
        return {"url": "https://evals-gomail.test/", "goal": "do the thing"}

    def step(self, action: str):
        self.steps += 1
        if self.step_delay:
            self.release.wait(timeout=self.step_delay)
        if self.raise_on_step is not None:
            raise self.raise_on_step
        done = self.finish_after is not None and self.steps >= self.finish_after
        return (
            {"url": f"https://evals-gomail.test/{self.steps}"},
            self.reward if done else 0.0,
            done,
            False,
            {},
        )

    def close(self) -> None:
        self.closed = True


class FakePolicy:
    """A policy that spends a fixed number of tokens and never finishes on its own."""

    def __init__(self, *, tokens_per_call: int = 0, source: str = "provider",
                 action: str = "click('1')", raises: Exception | None = None) -> None:
        self.level_name = "lean"
        self.tokens_per_call = tokens_per_call
        self.source = source
        self.action = action
        self.raises = raises
        self.calls = 0
        self.timeouts_seen: list[float | None] = []

    def propose(self, observation, history=(), timeout_s=None) -> Decision:
        self.calls += 1
        self.timeouts_seen.append(timeout_s)
        if self.raises is not None:
            raise self.raises
        usage = None
        if self.tokens_per_call:
            usage = Usage(
                prompt_tokens=self.tokens_per_call,
                completion_tokens=0,
                total_tokens=self.tokens_per_call,
                source=self.source,
            )
        return Decision(action=self.action, raw=f"reasoning\n```\n{self.action}\n```", usage=usage)


def run(task_id="v1.gomail-2", *, env=None, policy=None, output_path=None, **cap_kwargs):
    env = env if env is not None else FakeEnv()
    policy = policy if policy is not None else FakePolicy()
    caps = Caps(**{**LOOSE, **cap_kwargs})
    record = run_episode(
        task_id,
        env_factory=lambda: env,
        policy_factory=lambda: policy,
        caps=caps,
        output_path=output_path,
    )
    return record, env, policy


# --------------------------------------------------------------------------
# the step cap
# --------------------------------------------------------------------------


def test_the_step_caps_fires_in_isolation_and_names_itself():
    record, env, _ = run(max_steps=3)
    assert record.outcome == CAPPED
    assert record.cap == {"cap": STEPS, "limit": 3, "observed": 3, "unit": "steps"}
    assert record.steps == 3
    assert env.steps == 3
    # The other two caps were nowhere near, so this one fired on its own.
    assert record.tokens["charged"] == 0
    assert record.elapsed_s < LOOSE["max_wall_clock_s"]


def test_the_step_caps_control_does_not_fire_when_the_episode_finishes_first():
    record, _, _ = run(env=FakeEnv(finish_after=2), max_steps=25)
    assert record.outcome == COMPLETED
    assert record.cap is None
    assert record.steps == 2
    assert record.reward == 1.0
    assert record.env_terminated is True


# --------------------------------------------------------------------------
# the token cap
# --------------------------------------------------------------------------


def test_the_token_caps_fires_in_isolation_and_names_itself():
    policy = FakePolicy(tokens_per_call=100)
    record, env, _ = run(policy=policy, max_tokens=250)
    assert record.outcome == CAPPED
    assert record.cap == {"cap": TOKENS, "limit": 250, "observed": 300, "unit": "tokens"}
    # Fires on the call that crossed the line, not a step later: the third
    # action was never sent to the environment.
    assert policy.calls == 3
    assert env.steps == 2
    assert record.trace[-1]["executed"] is False


def test_the_token_caps_control_does_not_fire_under_a_generous_budget():
    policy = FakePolicy(tokens_per_call=100)
    record, _, _ = run(env=FakeEnv(finish_after=4), policy=policy, max_tokens=10_000)
    assert record.outcome == COMPLETED
    assert record.cap is None
    assert record.tokens["charged"] == 400


def test_the_token_caps_are_enforced_on_the_providers_numbers_when_they_exist():
    # z.ai returns `usage` on every response (entry 4), so in normal operation
    # the cap is enforced on z.ai's own count and nothing is estimated.
    policy = FakePolicy(tokens_per_call=100, source="provider")
    record, _, _ = run(policy=policy, max_tokens=250)
    assert record.tokens["provider_tokens"] == 300
    assert record.tokens["provider_calls"] == 3
    assert record.tokens["local_tokens"] == 0
    assert record.tokens["charged"] == 300  # charged exactly what the provider said


def test_the_token_caps_local_fallback_is_charged_with_the_measured_margin():
    # entry 6 measured cl100k_base understating z.ai's prompt_tokens by 2.2% at
    # worst. A cap enforced on an uncorrected local count is looser than it
    # reads, so the fallback marks up rather than hoping.
    policy = FakePolicy(tokens_per_call=1000, source="local")
    record, _, _ = run(policy=policy, max_tokens=10_000)
    assert record.tokens["local_tokens"] == 1000 * record.model_calls
    assert record.tokens["provider_tokens"] == 0
    assert record.tokens["local_undercount_applied"] == pytest.approx(1.022)
    assert record.tokens["charged"] == 1022 * record.model_calls
    assert record.tokens["charged"] > record.tokens["local_tokens"]


# --------------------------------------------------------------------------
# the wall-clock cap — the one that must assert on elapsed time
# --------------------------------------------------------------------------


def test_the_wall_clock_caps_bound_the_step_itself_not_just_the_gap_between_steps():
    # THE INHERITED LESSON. One step that hangs for 20 s, a 0.2 s budget. A cap
    # checked between steps would return the right reason 20 seconds late, and
    # a test that only read the reason would pass. So this asserts elapsed.
    env = FakeEnv(step_delay=20.0)
    started = time.monotonic()
    record, _, _ = run(env=env, max_wall_clock_s=0.2)
    outer_elapsed = time.monotonic() - started
    try:
        assert record.outcome == CAPPED
        assert record.cap["cap"] == WALL_CLOCK
        assert record.cap["limit"] == 0.2
        assert record.cap["observed"] >= 0.2
        assert record.cap["unit"] == "seconds"
        # The bound, asserted as a bound. 20 s of faked hang, and the call
        # returned in well under a second.
        assert outer_elapsed < 2.0, f"the loop took {outer_elapsed:.1f}s to give up"
        assert record.elapsed_s < 2.0
        # The hanging step is still hanging; Python cannot kill it. The record
        # says so instead of pretending cleanup happened.
        assert record.cleanup["wedged_on"] == "env.step"
        assert record.cleanup["env_closed"] is False
    finally:
        env.release.set()


def test_the_wall_clock_caps_control_does_not_fire_on_an_episode_that_finishes_in_time():
    started = time.monotonic()
    record, env, _ = run(env=FakeEnv(finish_after=3), max_wall_clock_s=30.0)
    assert record.outcome == COMPLETED
    assert record.cap is None
    assert record.elapsed_s < 5.0
    assert time.monotonic() - started < 5.0
    assert env.closed is True


def test_the_wall_clock_caps_deadline_is_what_the_policys_own_timeout_is_derived_from():
    # A per-operation timeout that does not know the episode budget is how nine
    # minutes fitted inside a 45 s bound. Every value handed to the policy is
    # the time left on the episode deadline.
    policy = FakePolicy()
    record, _, _ = run(env=FakeEnv(finish_after=3), policy=policy, max_wall_clock_s=30.0)
    assert record.outcome == COMPLETED
    assert len(policy.timeouts_seen) == 3
    assert all(0 < seen <= 30.0 for seen in policy.timeouts_seen)
    # Strictly decreasing: it is the remaining budget, not a fixed per-call bound.
    assert policy.timeouts_seen == sorted(policy.timeouts_seen, reverse=True)


def test_the_wall_clock_caps_fire_before_the_first_step_when_the_budget_is_already_gone():
    # A deadline that has already passed must end the episode, not start it.
    ticks = iter([0.0] + [100.0] * 50)
    record = run_episode(
        "v1.staynb-1",
        env_factory=FakeEnv,
        policy_factory=FakePolicy,
        caps=Caps(**{**LOOSE, "max_wall_clock_s": 1.0}),
        clock=lambda: next(ticks),
    )
    assert record.outcome == CAPPED
    assert record.cap["cap"] == WALL_CLOCK
    assert record.steps == 0


# --------------------------------------------------------------------------
# a cap ends the episode cleanly, and every episode records a reason
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cap_kwargs", "expected"),
    [
        ({"max_steps": 2}, STEPS),
        ({"max_tokens": 150}, TOKENS),
    ],
)
def test_capped_episodes_end_cleanly_and_release_the_environment(cap_kwargs, expected):
    policy = FakePolicy(tokens_per_call=100)
    record, env, _ = run(policy=policy, **cap_kwargs)
    assert record.outcome == CAPPED
    assert record.cap["cap"] == expected
    assert record.error is None            # a cap is not an exception
    assert env.closed is True              # and not a leak
    assert record.cleanup["wedged_on"] is None
    assert record.cleanup["env_closed"] is True


@pytest.mark.parametrize(
    ("kwargs", "outcome", "cap"),
    [
        ({"env": FakeEnv(finish_after=1)}, COMPLETED, None),
        ({"max_steps": 1}, CAPPED, STEPS),
        ({"policy": FakePolicy(tokens_per_call=100), "max_tokens": 50}, CAPPED, TOKENS),
        ({"env": FakeEnv(raise_on_step=ValueError("browser died"))}, ERRORED, None),
    ],
)
def test_every_episode_records_a_termination_reason_whatever_happened(kwargs, outcome, cap):
    # An episode ending with no recorded reason is a hole in feat-004's
    # accounting, so there is no path out of the loop that leaves one.
    record, _, _ = run(**kwargs)
    assert record.outcome == outcome
    assert record.termination()["outcome"] == outcome
    if cap is None:
        assert record.cap is None
    else:
        assert record.termination()["cap"] == cap
        assert "limit" in record.termination() and "observed" in record.termination()


def test_an_episode_that_breaks_is_recorded_rather_than_raised_at_the_caller():
    record, _, _ = run(env=FakeEnv(raise_on_step=ValueError("browser died")))
    assert record.outcome == ERRORED
    assert record.error["type"] == "ValueError"
    assert "browser died" in record.error["message"]
    assert record.cap is None


def test_a_policy_that_returns_no_action_is_recorded_rather_than_sent_to_the_browser():
    record, env, _ = run(policy=FakePolicy(action="   "))
    assert record.outcome == ERRORED
    assert record.error["type"] == "PolicyProducedNoAction"
    assert env.steps == 0


# --------------------------------------------------------------------------
# the cap-checking rules themselves
# --------------------------------------------------------------------------


def test_the_caps_reject_a_limit_that_could_never_fire():
    for bad in ({"max_steps": 0}, {"max_tokens": -1}, {"max_wall_clock_s": 0.0}):
        with pytest.raises(ValueError):
            Caps(**bad)


def test_the_caps_report_a_deterministic_one_when_more_than_one_is_reached():
    # Two caps can cross on the same check. "Whichever the code tested first" is
    # not a reason, so the order is fixed: wall clock, then tokens, then steps.
    caps = Caps(max_steps=1, max_tokens=100, max_wall_clock_s=10.0)
    ledger = TokenLedger()
    ledger.add(Usage(prompt_tokens=100, completion_tokens=0, total_tokens=100))

    live = Deadline(10.0, clock=iter([0.0, 1.0, 1.0, 1.0]).__next__)
    assert check(caps, live, ledger, steps=1).cap == TOKENS

    expired = Deadline(1.0, clock=iter([0.0] + [99.0] * 8).__next__)
    assert check(caps, expired, ledger, steps=1).cap == WALL_CLOCK

    assert check(caps, live, TokenLedger(), steps=1).cap == STEPS
    assert check(caps, live, TokenLedger(), steps=0) is None


def test_a_cap_hit_describes_itself_for_a_human_and_for_a_machine():
    hit = CapHit(cap=WALL_CLOCK, limit=300.0, observed=300.4, unit="seconds")
    assert hit.to_dict() == {
        "cap": "wall_clock", "limit": 300.0, "observed": 300.4, "unit": "seconds",
    }
    assert "wall_clock cap" in hit.describe()


# --------------------------------------------------------------------------
# concurrency safety — three of these run in three processes (entry 7)
# --------------------------------------------------------------------------


def test_two_concurrent_episodes_keep_their_caps_and_their_accounting_apart():
    # feat-004 runs three of these at once. Anything shared between episodes —
    # a client, a clock, a counter, a path — would show up here as one
    # episode's budget being spent by the other.
    by_steps = FakeEnv()
    by_tokens = FakeEnv()
    a_policy = FakePolicy(tokens_per_call=100)
    b_policy = FakePolicy(tokens_per_call=100)

    def episode_a():
        return run_episode(
            "v1.gomail-2",
            env_factory=lambda: by_steps,
            policy_factory=lambda: a_policy,
            caps=Caps(**{**LOOSE, "max_steps": 2}),
        )

    def episode_b():
        return run_episode(
            "v1.staynb-1",
            env_factory=lambda: by_tokens,
            policy_factory=lambda: b_policy,
            caps=Caps(**{**LOOSE, "max_tokens": 250}),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = (f.result(timeout=30) for f in [pool.submit(episode_a), pool.submit(episode_b)])

    assert a.task_id == "v1.gomail-2" and b.task_id == "v1.staynb-1"
    # Each ended on its own cap, at its own limit.
    assert a.cap == {"cap": STEPS, "limit": 2, "observed": 2, "unit": "steps"}
    assert b.cap == {"cap": TOKENS, "limit": 250, "observed": 300, "unit": "tokens"}
    # Each counted only its own tokens and its own steps.
    assert (a.steps, a.model_calls, a.tokens["charged"]) == (2, 2, 200)
    assert (b.steps, b.model_calls, b.tokens["charged"]) == (2, 3, 300)
    assert (by_steps.steps, by_tokens.steps) == (2, 2)
    assert by_steps.closed and by_tokens.closed


def test_nothing_is_written_anywhere_unless_the_caller_names_a_path(tmp_path):
    before = sorted(p.name for p in tmp_path.iterdir())
    record, _, _ = run(env=FakeEnv(finish_after=1))
    assert record.output_path is None
    assert record.output_error is None
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_the_record_is_written_only_to_the_path_the_caller_gave(tmp_path):
    import json

    out = tmp_path / "runs" / "some-run-id" / "v1.gomail-2.json"
    record, _, _ = run(env=FakeEnv(finish_after=1), output_path=out, max_steps=25)
    assert out.exists()
    written = json.loads(out.read_text())
    assert written["task_id"] == "v1.gomail-2"
    assert written["termination"] == {"outcome": COMPLETED}
    assert written["caps"]["max_steps"] == 25
    assert record.output_error is None


def test_capped_log_lines_carry_the_task_id_so_interleaved_output_stays_readable(caplog):
    with caplog.at_level(logging.INFO, logger="web_agent_eval.episode"):
        run("v1.dashdish-3", max_steps=2)
    messages = [r.getMessage() for r in caplog.records]
    assert messages, "the episode logged nothing"
    assert all(m.startswith("[v1.dashdish-3] ") for m in messages), messages
    assert any("steps cap" in m for m in messages)
