"""A minimal GLM agent, built only to get feat-001's [GATE] through.

This is deliberately the smallest thing that can drive one REAL task end to end.
It is NOT the project's agent: feat-002 owns the observation serializer and
feat-003 owns the loop and its caps. Nothing here should be treated as a design
decision for either — it exists to prove GLM can drive agisdk at all.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

from agisdk.REAL.browsergym.core.action.highlevel import HighLevelActionSet
from agisdk.REAL.browsergym.core.action.parsers import highlevel_action_parser
from agisdk.REAL.browsergym.experiments import AbstractAgentArgs, Agent

from web_agent_eval import glm

_FENCE = re.compile(r"```(?:python)?\s*(.+?)\s*```", re.DOTALL)


def extract_action(text: str) -> str:
    """Pull exactly one action call out of the model's narration.

    Handing browsergym the raw reply does not work, and the failure is not
    obvious. Its parser scans the WHOLE string, pyparsing skips whitespace, and
    a second match is rejected as a multi-action — so ordinary English prose
    parses as a function call:

        "The first email's checkbox is already checked (checked='true')."
                                              -> checked('true')
        'I am viewing the first email ("Your Account Statement is Ready")'
                                              -> email('Your Account Statement is Ready')

    Both of those really did abort a step in the first gate run. The last call
    in the reply is the intended action; everything before it is prose.
    """
    fenced = _FENCE.findall(text)
    candidate = fenced[-1] if fenced else text
    calls = [call for match in highlevel_action_parser.search_string(candidate).as_list()
             for call in match]
    if not calls:
        return candidate.strip()
    name, args = calls[-1]
    return f"{name}(" + ", ".join(repr(arg) for arg in args) + ")"

SYSTEM_PROMPT = """\
You are a web agent. You are given a goal, the accessibility tree of the current
page, and the actions you may take.

Reply with one short line of reasoning and then EXACTLY ONE action inside a
fenced code block. The code block must contain a single function call and
nothing else — no second call, no commentary inside the fence.

As soon as the goal is achieved, call send_msg_to_user("...") with the answer or
a short confirmation. That call is the only thing that ends the episode and
triggers scoring, so do not keep exploring once the goal is done.
"""


class GateAgent(Agent):
    def __init__(self, model_name: str, max_axtree_chars: int, trace_path: str | None) -> None:
        self.model_name = model_name
        self.max_axtree_chars = max_axtree_chars
        self.trace_path = Path(trace_path) if trace_path else None
        if self.trace_path:
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            self.trace_path.write_text("")
        self.client = glm.make_client()
        self.action_set = HighLevelActionSet(
            subsets=["chat", "bid", "infeas"], strict=False, multiaction=False, demo_mode="off"
        )
        self.history: list[str] = []
        # Recorded per step so feat-005 has a shape to build on, and so this run
        # can report real token numbers instead of an estimate.
        self.usage: list[dict[str, int]] = []

    def obs_preprocessor(self, obs: dict) -> dict:
        from agisdk.REAL.browsergym.experiments.agent import default_obs_preprocessor

        obs = default_obs_preprocessor(obs)
        obs.pop("screenshot", None)  # glm-4.6 is text-only
        return obs

    def _prompt(self, obs: dict) -> str:
        goal = obs.get("goal") or str(obs.get("goal_object", ""))
        axtree = (obs.get("axtree_txt") or "")[: self.max_axtree_chars]
        parts = [
            f"# Goal\n{goal}",
            f"# Current URL\n{obs.get('url', '')}",
            f"# Accessibility tree\n{axtree}",
            f"# Action space\n{self.action_set.describe(with_long_description=False, with_examples=True)}",
        ]
        if self.history:
            parts.append("# Actions already taken\n" + "\n".join(self.history))
        if obs.get("last_action_error"):
            parts.append(f"# Error from the last action\n{obs['last_action_error']}")
        parts.append("# Next action")
        return "\n\n".join(parts)

    def get_action(self, obs: dict) -> tuple[str, dict]:
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": self._prompt(obs)},
            ],
            temperature=0.0,
            max_tokens=1024,
            # glm-4.6 reasons by default and spends the token budget on thinking
            # it never returns. The gate does not need it.
            extra_body={"thinking": {"type": "disabled"}},
        )
        if response.usage is not None:
            self.usage.append(
                {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
            )
        text = response.choices[0].message.content or ""
        action = extract_action(text)
        self.history.append(action)

        if self.trace_path:
            with self.trace_path.open("a") as fh:
                fh.write(json.dumps({
                    "step": len(self.history),
                    "url": obs.get("url"),
                    "raw": text,
                    "action": action,
                    "last_action_error": obs.get("last_action_error") or None,
                    "usage": self.usage[-1] if self.usage else None,
                }) + "\n")

        return action, {}


@dataclasses.dataclass
class GateAgentArgs(AbstractAgentArgs):
    """`harness(agentargs=...)` is the seam a custom model plugs into.

    The built-in agent routes on model-name prefix (`gpt-`, `claude-`,
    `openrouter/`, `local/`) and has no base_url parameter, so GLM cannot go
    through it. This seam has no such constraint.
    """

    model_name: str = glm.DEFAULT_MODEL
    max_axtree_chars: int = 12000
    trace_path: str | None = None

    def make_agent(self) -> GateAgent:
        return GateAgent(
            model_name=self.model_name,
            max_axtree_chars=self.max_axtree_chars,
            trace_path=self.trace_path,
        )
