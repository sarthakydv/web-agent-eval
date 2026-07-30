"""The GLM policy, over a real captured observation. No network.

The client is faked; everything else is the real thing — the real serializer,
the real action space, the real extraction, the real usage handling. What is
being checked is the wiring the loop depends on: that richness comes in as a
parameter (feat-007's seam, entry 6), that the provider's own usage is used when
it exists, and that a reply is never handed to browsergym unextracted (entry 4).
"""

from __future__ import annotations

import pytest

from web_agent_eval import fixtures
from web_agent_eval.observation import LEAN, RICH, Richness
from web_agent_eval.policy import DEFAULT_MAX_REPLY_TOKENS, GlmPolicy

LOADED = "v1.gomail-2_step02"


class FakeUsage:
    def __init__(self, prompt, completion):
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = prompt + completion


class FakeResponse:
    def __init__(self, content, usage):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]
        self.usage = usage


_SENTINEL = object()


class FakeClient:
    """Records what was sent, returns what it was told to."""

    def __init__(self, content="Clicking it.\n\nclick('209')", usage=_SENTINEL):
        self.content = content
        self.usage = FakeUsage(2000, 40) if usage is _SENTINEL else usage
        self.calls = []
        self.chat = type("Chat", (), {"completions": self})()

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse(self.content, self.usage)


@pytest.fixture(scope="module")
def loaded():
    return fixtures.load_observation(LOADED)


def test_the_policy_extracts_one_action_rather_than_passing_the_reply_through(loaded):
    # Entry 4: browsergym's parser scans the whole reply, so prose becomes a
    # second call and the step dies with "Received a multi-action".
    client = FakeClient(content="The checkbox is already checked (checked='true').\n\nclick('209')")
    decision = GlmPolicy(client=client).propose(loaded)
    assert decision.action == "click('209')"
    assert "checked" in decision.raw


def test_the_policy_charges_the_providers_usage_when_it_is_there(loaded):
    decision = GlmPolicy(client=FakeClient()).propose(loaded)
    assert decision.usage.source == "provider"
    assert decision.usage.total_tokens == 2040


def test_the_policy_falls_back_to_a_local_count_when_the_provider_sends_none(loaded):
    decision = GlmPolicy(client=FakeClient(usage=None)).propose(loaded)
    assert decision.usage.source == "local"
    # The whole prompt was counted, not just the observation.
    assert decision.usage.prompt_tokens > decision.observation_tokens


def test_richness_is_a_parameter_the_policy_consumes_rather_than_a_level_it_picks(loaded):
    lean = GlmPolicy(level=LEAN, client=FakeClient()).propose(loaded)
    rich = GlmPolicy(level=RICH, client=FakeClient()).propose(loaded)
    assert rich.observation_tokens > lean.observation_tokens * 2
    # feat-007 varies exactly this object, and a caller-defined rung must work
    # without an edit here — otherwise the ablation compares a code change too.
    custom = GlmPolicy(
        level=Richness(name="coords-only",
                       axtree_options={"filter_visible_only": True, "with_center_coords": True}),
        client=FakeClient(),
    )
    assert custom.level_name == "coords-only"
    assert 'center="(' in custom.prompt(loaded, ())[0]


def test_the_settings_that_must_be_held_constant_across_arms_are_sent_every_call(loaded):
    # Entry 4: glm-4.6 reasons by default and spends the whole budget on
    # thinking it never returns. Entry 9: reasoning spend scales with the cap.
    client = FakeClient()
    GlmPolicy(client=client).propose(loaded, ("click('1')",), timeout_s=12.5)
    sent = client.calls[0]
    assert sent["model"] == "glm-4.6"
    assert sent["temperature"] == 0.0
    assert sent["max_tokens"] == DEFAULT_MAX_REPLY_TOKENS
    assert sent["extra_body"] == {"thinking": {"type": "disabled"}}
    # The request timeout is the episode's remaining budget, handed down.
    assert sent["timeout"] == 12.5
    assert "# Actions already taken\nclick('1')" in sent["messages"][1]["content"]
