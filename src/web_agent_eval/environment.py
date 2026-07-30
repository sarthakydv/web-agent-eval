"""The "observe" and "act" half: a REAL task as a plain gym environment.

`feat-001`'s gate went through `REAL.harness`, which owns the loop itself — its
own `max_steps`, its own step ordering, its own termination. That is the wrong
shape for `feat-003`, whose entire subject is the loop and its caps, so this
adapter takes the raw environment `agisdk` builds and leaves the loop to
`episode.py`.

**`max_episode_steps` is deliberately left unset.** gym's `TimeLimit` wrapper
would truncate the episode at its own count, and a run truncated by the wrapper
records as `completed`/`truncated` rather than `capped` — which is precisely the
distinction entry 7 publishes separately. The step cap has to be this project's,
or the accounting says the wrong thing.

**No `default_obs_preprocessor`.** agisdk's preprocessor deletes
`axtree_object` and `dom_object`, and the serializer would then fall back to a
pre-flattened tree — it says so in the rendered text, but a fallback is not the
richness level `feat-007` asked for. The raw observation goes to the policy
untouched.

**Honest status.** Everything here is thin — it constructs `EnvArgs`, calls
`make_env`, and unwraps gym's tuples — but it is exercised by no test in this
suite, because it needs a browser and the hosted replica sites. `feat-003`'s
tests run the loop against fakes on purpose: the caps are what is being verified
and a browser would make that verification slow and flaky. The first real
exercise of this class is `feat-004`'s first run, and that is stated here rather
than implied by its presence.
"""

from __future__ import annotations

from agisdk.REAL.browsergym.core.action.highlevel import HighLevelActionSet
from agisdk.REAL.browsergym.experiments.loop import EnvArgs


class AgisdkEnvironment:
    """One REAL task, gym-shaped. Built per episode, on the episode's worker thread.

    Playwright's sync API has thread affinity, so this object is constructed and
    driven from a single thread — `run_episode` calls the factory through the
    same `BoundedRunner` that later calls `reset`, `step` and `close`.
    """

    def __init__(
        self,
        task_id: str,
        *,
        action_set: HighLevelActionSet | None = None,
        headless: bool = True,
        seed: int | None = None,
        exp_dir=None,
        **env_kwargs,
    ) -> None:
        self.task_id = task_id
        self.seed = seed
        self.action_set = action_set or HighLevelActionSet(
            subsets=["chat", "bid", "infeas"], strict=False, multiaction=False, demo_mode="off"
        )
        env_args = EnvArgs(
            task_name=task_id,
            task_seed=seed,
            # Not a mistake — see the module docstring. The step cap is ours.
            max_steps=None,
            headless=headless,
            **env_kwargs,
        )
        self.env = env_args.make_env(
            action_mapping=self.action_set.to_python_code,
            exp_dir=exp_dir,
        )

    def reset(self) -> dict:
        obs, _info = self.env.reset(seed=self.seed)
        return obs

    def step(self, action: str) -> tuple[dict, float, bool, bool, dict]:
        return self.env.step(action)

    def close(self) -> None:
        self.env.close()


def agisdk_env_factory(task_id: str, **kwargs):
    """A zero-argument factory for `run_episode`, so the browser is built per episode."""

    def factory() -> AgisdkEnvironment:
        return AgisdkEnvironment(task_id, **kwargs)

    return factory
