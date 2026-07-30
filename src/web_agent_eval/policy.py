"""The GLM policy: one observation in, one action out, one usage record out.

This is the "decide" half of the loop. It owns nothing global — a policy is
built per episode by `run_episode`, and it builds its own z.ai client inside its
own constructor, so three concurrent episodes in three processes share no
client, no counter and no history.

**Richness is consumed, not chosen here.** `feat-002` made the observation
serializer take a `Richness` object (entry 6), and `feat-007`'s ablation varies
exactly that object. So the policy takes one and passes it through; it does not
hardcode a level, and a caller-defined level works without editing this file.

**Reasoning is disabled and the reply cap is stated.** `glm-4.6` reasons by
default and will spend the whole completion budget on thinking it never returns
(entry 4), and entry 9 measured reasoning spend scaling with the token cap.
Both are settings this project must state rather than inherit: `thinking` is
disabled, `max_reply_tokens` is 1024, and both are held constant across every
arm of `feat-006` and `feat-007`.
"""

from __future__ import annotations

from agisdk.REAL.browsergym.core.action.highlevel import HighLevelActionSet

from web_agent_eval import glm
from web_agent_eval.action import extract_action
from web_agent_eval.caps import TokenLedger, Usage
from web_agent_eval.episode import Decision
from web_agent_eval.observation import LEAN, Richness, level_by_name, serialize

#: The completion cap on one model call. Entry 9: on a reasoning model the token
#: cap is an input to the tokens-per-task claim, not only a safety bound.
DEFAULT_MAX_REPLY_TOKENS = 1024

SYSTEM_PROMPT = """\
You are a web agent. You are given a goal, a rendering of the current page, and
the actions you may take.

Reply with one short line of reasoning and then EXACTLY ONE action inside a
fenced code block. The code block must contain a single function call and
nothing else — no second call, no commentary inside the fence.

As soon as the goal is achieved, call send_msg_to_user("...") with the answer or
a short confirmation. That call is the only thing that ends the episode and
triggers scoring, so do not keep exploring once the goal is done.
"""


class GlmPolicy:
    """Drives `glm-4.6` through z.ai's coding-plan endpoint. Built per episode."""

    def __init__(
        self,
        *,
        level: Richness | str = LEAN,
        model: str = glm.DEFAULT_MODEL,
        max_reply_tokens: int = DEFAULT_MAX_REPLY_TOKENS,
        temperature: float = 0.0,
        client=None,
        ledger: TokenLedger | None = None,
    ) -> None:
        self.level = level_by_name(level) if isinstance(level, str) else level
        self.level_name = self.level.name
        self.model = model
        self.max_reply_tokens = max_reply_tokens
        self.temperature = temperature
        # Per episode. `glm.make_client()` builds a fresh client every call and
        # this class never caches one on the module.
        self.client = client if client is not None else glm.make_client()
        # Only used when a response arrives without a `usage` field.
        self._ledger = ledger or TokenLedger()
        self.action_set = HighLevelActionSet(
            subsets=["chat", "bid", "infeas"], strict=False, multiaction=False, demo_mode="off"
        )

    def prompt(self, observation: dict, history: tuple[str, ...]) -> tuple[str, int, dict]:
        rendered = serialize(observation, self.level)
        parts = [
            rendered.text,
            "# Action space\n"
            + self.action_set.describe(with_long_description=False, with_examples=True),
        ]
        if history:
            parts.append("# Actions already taken\n" + "\n".join(history))
        parts.append("# Next action")
        return "\n\n".join(parts), rendered.tokens, dict(rendered.truncated)

    def propose(
        self,
        observation: dict,
        history: tuple[str, ...] = (),
        timeout_s: float | None = None,
    ) -> Decision:
        user, observation_tokens, truncated = self.prompt(observation, history)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]
        kwargs = {}
        if timeout_s is not None and timeout_s > 0:
            # Belt to the loop's braces. The episode deadline is enforced by
            # `BoundedRunner` whatever the SDK does; this simply stops the SDK
            # from holding a socket open past the point where the answer could
            # still be used. It is derived from the deadline, never set apart
            # from it — a sub-timeout that does not know the episode budget is
            # how the predecessor fitted nine minutes inside a 45 s bound.
            kwargs["timeout"] = timeout_s

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_reply_tokens,
            extra_body={"thinking": {"type": "disabled"}},
            **kwargs,
        )
        raw = response.choices[0].message.content or ""
        usage = _usage_from(response)
        if usage is None:
            # No provider numbers on this response: reconstruct locally and let
            # the ledger apply the measured undercount margin (entry 6).
            usage = self._ledger.local_usage(SYSTEM_PROMPT + user, raw)
        return Decision(
            action=extract_action(raw),
            raw=raw,
            usage=usage,
            observation_tokens=observation_tokens,
            observation_truncated=truncated,
        )


def _usage_from(response) -> Usage | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    total = getattr(usage, "total_tokens", None)
    if total is None:
        return None
    return Usage(
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        total_tokens=total,
        source="provider",
    )


def glm_policy_factory(level: Richness | str = LEAN, **kwargs):
    """A zero-argument factory for `run_episode`, so the client is built per episode."""

    def factory() -> GlmPolicy:
        return GlmPolicy(level=level, **kwargs)

    return factory
