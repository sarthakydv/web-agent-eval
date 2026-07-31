"""feat-005: the judge is called, it is called against OpenAI, and it is counted.

Offline. No key is used and no request leaves the machine — the openai SDK call
is stubbed *underneath* agisdk, so agisdk's own `generate_from_model`, its own
`OpenAI()` construction and its own prompt all execute for real and only the
HTTP round trip is replaced. That is the point: the thing being tested is
whether this project's instrumentation sits in the path agisdk actually takes,
and a test that stubbed `generate_from_model` itself would pass while the
instrumentation measured nothing.

Both failure modes from `judge.py` are tested from both sides, per AGENTS.md's
control rule: a check that has only ever been seen to pass is not evidence.
"""

from __future__ import annotations

import pytest

from web_agent_eval import judge


@pytest.fixture(autouse=True)
def clean_judge(monkeypatch):
    """Every test starts with a fresh ledger, no patches, and no leaked env."""
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    judge.reset()
    yield
    judge.uninstall()
    judge.reset()


class FakeUsage:
    prompt_tokens = 160
    completion_tokens = 3
    total_tokens = 163
    prompt_tokens_details = None


class FakeResponse:
    """Shaped like an openai chat completion, and no more."""

    def __init__(self, content: str = "1.0", model: str = "gpt-4.1-2025-04-14") -> None:
        self.model = model
        self.usage = FakeUsage()
        message = type("M", (), {"content": content})()
        self.choices = [type("C", (), {"message": message})()]


def stub_openai(content: str = "1.0", model: str = "gpt-4.1-2025-04-14") -> list[dict]:
    """Replace only the real HTTP call, once the instrumentation is installed.

    `judge.install()` has already wrapped `Completions.create`; this swaps the
    *original* it delegates to. Everything above it — agisdk's judge function,
    the client construction, the prompt — is untouched.
    """
    seen: list[dict] = []

    def fake_create(self, *args, **kwargs):
        seen.append({"model": kwargs.get("model"), "base_url": str(self._client.base_url)})
        return FakeResponse(content, model)

    judge._ORIGINALS["create"] = fake_create
    return seen


def evaluator(rubric: str = "Does the answer say 4?"):
    from agisdk.REAL.browsergym.webclones.evaluate import WebCloneEvaluator

    return WebCloneEvaluator.__new__(WebCloneEvaluator), rubric


# --------------------------------------------------------------------------
# failure mode 2: the judge silently running somewhere else
# --------------------------------------------------------------------------


def test_require_accepts_a_judge_pointed_at_openai():
    info = judge.require()
    assert info["host"] == "api.openai.com"
    assert info["is_openai"] is True
    assert info["model_default"] == "gpt-4.1"


def test_require_refuses_when_openai_base_url_leaks_to_zai(monkeypatch):
    """The control for the test above. Entry 9: `OpenAI()` reads this variable."""
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.z.ai/api/coding/paas/v4/")
    with pytest.raises(judge.JudgeMisrouted) as exc:
        judge.require()
    assert "api.z.ai" in str(exc.value)
    assert judge.endpoint()["is_openai"] is False


def test_require_refuses_when_the_key_is_absent(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    with pytest.raises(judge.JudgeUnavailable):
        judge.require()


def test_the_optional_glm_judge_comparison_can_opt_out_explicitly(monkeypatch):
    """Entry 10's optional finding is allowed — but only by asking for it."""
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.z.ai/api/coding/paas/v4/")
    info = judge.require(allow_non_openai=True)
    assert info["host"] == "api.z.ai"


# --------------------------------------------------------------------------
# failure mode 1: the judge never called, and a score appearing anyway
# --------------------------------------------------------------------------


def test_a_judged_eval_records_the_call_its_endpoint_and_its_usage():
    judge.install()
    seen = stub_openai(content="1.0")
    ev, rubric = evaluator()
    ev.llm = judge.default_judge_model()

    is_correct, info = ev.evaluate_with_llm("the answer is 4", rubric)

    assert is_correct is True
    assert info["similarity"] == 1.0
    # agisdk really did construct its own client and ask for its own model.
    assert seen == [{"model": "gpt-4.1", "base_url": "https://api.openai.com/v1/"}]

    ledger = judge.ledger().to_dict()
    assert ledger["judge_calls"] == 1
    call = ledger["calls"][0]
    assert call["host"] == "api.openai.com"
    assert call["requested_model"] == "gpt-4.1"
    assert call["served_model"] == "gpt-4.1-2025-04-14"
    assert (call["prompt_tokens"], call["completion_tokens"]) == (160, 3)
    assert ledger["tokens"] == {"prompt": 160, "completion": 3, "cached_prompt": 0, "total": 163}
    assert ledger["llm_evals"][0]["similarity"] == 1.0
    assert ledger["llm_evals"][0]["is_correct"] is True


def test_a_call_made_outside_the_judge_window_is_not_counted():
    """The control: the agent's own model calls go through the same patched
    method in the same process, and counting them as judge tokens would inflate
    the judge's dollar column with the agent's spend."""
    from openai import OpenAI

    judge.install()
    stub_openai()
    client = OpenAI(api_key="sk-agent", base_url="https://api.z.ai/api/coding/paas/v4/")
    client.chat.completions.create(model="glm-4.6", messages=[{"role": "user", "content": "hi"}])

    ledger = judge.ledger().to_dict()
    assert ledger["judge_calls"] == 0
    assert ledger["tokens"]["total"] == 0


def test_an_unevaluated_episode_reports_zero_calls_not_a_grade():
    """The shape of the real failure mode. agisdk's `validate()` only evaluates
    once the agent has sent a message, so an episode that capped without
    answering leaves `evaluate_calls == 0`. That is a real zero reward, but it
    is not a grade, and the ledger has to be able to say so."""
    judge.install()
    stub_openai()
    ledger = judge.ledger().to_dict()
    assert ledger["evaluate_calls"] == 0
    assert ledger["judge_calls"] == 0
    assert ledger["llm_evals"] == []


def test_the_instrumentation_patches_the_reference_agisdk_actually_calls():
    """`evaluate.py` did `from ... utils import generate_from_model`, so it holds
    its own reference. Patching `utils` would patch a name nobody calls, and the
    ledger would report a clean zero for every task — a passing check measuring
    nothing, which is the exact bug class AGENTS.md's control rule exists for."""
    from agisdk.REAL.browsergym.webclones import evaluate as evaluate_module
    from agisdk.REAL.browsergym.webclones import utils as utils_module

    before = evaluate_module.generate_from_model
    judge.install()
    assert evaluate_module.generate_from_model is not before
    assert utils_module.generate_from_model is not evaluate_module.generate_from_model


def test_a_judge_error_is_recorded_and_still_raised():
    judge.install()

    def boom(self, *args, **kwargs):
        raise RuntimeError("judge exploded")

    judge._ORIGINALS["create"] = boom
    ev, rubric = evaluator()
    ev.llm = "gpt-4.1"
    with pytest.raises(RuntimeError):
        ev.evaluate_with_llm("anything", rubric)

    ledger = judge.ledger().to_dict()
    assert ledger["judge_calls"] == 1
    assert "judge exploded" in ledger["calls"][0]["error"]
    assert ledger["errors"]


# --------------------------------------------------------------------------
# the population this judge unlocks, and the price it is billed at
# --------------------------------------------------------------------------


def test_the_judged_task_count_matches_what_the_manifest_excludes():
    """Entry 5's arithmetic, checked against the installed task set rather than
    restated: 112 tasks, 10 unreachable, 60 judged, 102 - 55 = 47 scorable on
    z.ai's key alone. If agisdk's task set changes, this fails instead of the
    denominator quietly changing meaning."""
    from web_agent_eval import manifest as manifest_module

    judged = manifest_module.judged_task_ids()
    full, _ = manifest_module.population("112")
    reachable, _ = manifest_module.population("102")
    no_judge, _ = manifest_module.population("47")

    assert len(full) == 112
    assert len(judged) == 60
    assert len(reachable) == 102
    assert len(no_judge) == 47
    assert len([t for t in reachable if t in judged]) == 55
    assert not [t for t in no_judge if t in judged]


def test_task_needs_judge_agrees_with_the_task_table():
    assert judge.task_needs_judge("v1.dashdish-1") is True
    assert judge.task_needs_judge("v1.gomail-2") is False
    assert judge.judged_in(["v1.dashdish-1", "v1.gomail-2"]) == ["v1.dashdish-1"]


def test_judge_cost_is_the_published_rate_times_measured_tokens():
    # 1M prompt tokens at $2.00 and 1M completion at $8.00.
    assert judge.usd(1_000_000, 0) == pytest.approx(2.00)
    assert judge.usd(0, 1_000_000) == pytest.approx(8.00)
    # Cached prompt tokens bill at the cached rate and are not double counted.
    assert judge.usd(1_000_000, 0, 1_000_000) == pytest.approx(0.50)
    assert judge.usd(1_000_000, 0, 400_000) == pytest.approx(0.6 * 2.00 + 0.4 * 0.50)
    # A cached count larger than the prompt cannot make the bill negative.
    assert judge.usd(100, 0, 10_000) == pytest.approx(100 * 0.50 / 1_000_000)
