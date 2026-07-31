"""REAL's own judge: proving it ran, where it ran, and what it cost.

`agisdk` grades `llm_boolean` evals with an LLM judge — `client = OpenAI()`
built with **no arguments** (`browsergym/webclones/utils.py`), model defaulting
to `gpt-4.1` (`browsergym/webclones/evaluate.py`). 55 of the 102 reachable v1
tasks have at least one such eval, so this judge is what makes the population
102 instead of 47 and what makes the number comparable to REAL's published
baseline. See docs/DECISIONS.md entry 10.

Two failure modes look exactly like success, and this module exists to make
both impossible to miss.

**1. The judge is never called and the score comes out anyway.** `validate()`
only evaluates when the agent has sent a message (`len(assistant_messages) > 1`),
so an agent that caps out without answering gets `reward = 0.0` from a code path
where `evaluate()` never ran. That is a legitimate zero — but it is *not* the
judge grading the answer as wrong, and a run that confused the two would report
a judged score that was never judged. `JudgeLedger` counts `evaluate()` calls
and judge calls separately, so "the judge said no" and "the judge was never
asked" are different rows.

**2. `OPENAI_BASE_URL` leaks and the judge quietly runs on z.ai.** `OpenAI()`
with no arguments reads `OPENAI_BASE_URL` from the environment. If that variable
is set — `.env` carries it commented out for the optional GLM-as-judge
comparison — then the "OpenAI judge" is GLM, every grade is produced by the same
family of model being measured, and nothing in the output says so. `require()`
refuses to run in that state.

**How the proof is taken.** Nothing here reimplements agisdk's judge. The real
`generate_from_model` runs verbatim; it is *wrapped* only to mark the window in
which it is executing, and `openai`'s `Completions.create` is patched to record
any call made inside that window — its client's actual `base_url`, the model
requested, the model the server reported back, and the usage. So the base URL in
the record is the one the HTTP client really used, not one this module asserted.

**Scope.** One process, one episode (entry 12: one process per task, never
reused), so the ledger is module-level and per-process by design.
"""

from __future__ import annotations

import inspect
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from urllib.parse import urlsplit

#: The host a judge that is really OpenAI's must be talking to.
OPENAI_HOST = "api.openai.com"

#: Published 2026-07-31 at https://developers.openai.com/api/docs/pricing,
#: Standard mode. USD per 1M tokens. Unlike z.ai's Coding Plan — which
#: publishes no rate for this key, so agent cost is reported in tokens alone
#: (docs/DECISIONS.md entry 6) — OpenAI publishes one, so judge cost can be
#: stated in dollars without estimating anything. The two are never summed.
GPT_41_USD_PER_1M = {"input": 2.00, "cached_input": 0.50, "output": 8.00}
PRICE_SOURCE = "https://developers.openai.com/api/docs/pricing (Standard), retrieved 2026-07-31"


class JudgeMisrouted(RuntimeError):
    """The judge is not pointed where the score claims it is."""


class JudgeUnavailable(RuntimeError):
    """The judge cannot run at all — no key."""


# --------------------------------------------------------------------------
# what agisdk actually defaults to, read from agisdk
# --------------------------------------------------------------------------


def default_judge_model() -> str:
    """agisdk's judge model, read from its own signature rather than restated.

    A constant copied out of a dependency is a constant that goes stale in
    silence. This reads `WebCloneEvaluator.__init__`'s `llm` default, so an
    agisdk upgrade that changes the judge shows up as a changed number here
    instead of a wrong claim in the README.
    """
    from agisdk.REAL.browsergym.webclones.evaluate import WebCloneEvaluator

    default = inspect.signature(WebCloneEvaluator.__init__).parameters["llm"].default
    if not isinstance(default, str) or not default:
        raise JudgeMisrouted(
            f"agisdk's WebCloneEvaluator no longer defaults its judge model to a string "
            f"(got {default!r}); the scored population's provenance has changed"
        )
    return default


def task_needs_judge(task_id: str) -> bool:
    """Does this task have an `llm_boolean` eval — i.e. is it one of the 55?

    Read from the installed task configs, the same source `manifest.population`
    derives its counts from, so the two can never disagree.
    """
    from web_agent_eval.manifest import judged_task_ids

    return task_id in judged_task_ids()


def judged_in(task_ids: list[str]) -> list[str]:
    """Which of these tasks need the judge. Used to decide whether a run may start."""
    from web_agent_eval.manifest import judged_task_ids

    judged = judged_task_ids()
    return [t for t in task_ids if t in judged]


def endpoint() -> dict:
    """Where a no-argument `OpenAI()` would actually send the judge's calls.

    Constructed the same way agisdk constructs it, so this reports the real
    resolved configuration — base URL and key presence — and not what `.env`
    was intended to say.
    """
    from openai import OpenAI

    env_base_url = os.environ.get("OPENAI_BASE_URL")
    key = os.environ.get("OPENAI_API_KEY") or ""
    info = {
        "OPENAI_BASE_URL_env": env_base_url,
        "OPENAI_API_KEY_set": bool(key.strip()),
        "OPENAI_API_KEY_prefix": (key[:6] + "…") if key.strip() else None,
        "model_default": None,
        "base_url": None,
        "host": None,
        "is_openai": False,
    }
    try:
        info["model_default"] = default_judge_model()
    except Exception as exc:  # noqa: BLE001 — reported, not raised, so require() decides
        info["model_default_error"] = f"{type(exc).__name__}: {exc}"
    if not info["OPENAI_API_KEY_set"]:
        return info
    client = OpenAI()
    info["base_url"] = str(client.base_url)
    info["host"] = urlsplit(info["base_url"]).hostname
    info["is_openai"] = info["host"] == OPENAI_HOST
    return info


def require(*, allow_non_openai: bool = False) -> dict:
    """Assert the judge is OpenAI's `gpt-4.1`, or refuse to produce a score.

    Called before any run that intends to publish a judged number. Both of the
    failure modes in the module docstring are caught here as errors rather than
    discovered afterwards in a number that already looks fine.

    `allow_non_openai=True` is only for the optional GLM-as-judge comparison in
    entry 10, which is explicitly not the headline.
    """
    info = endpoint()
    if not info["OPENAI_API_KEY_set"]:
        raise JudgeUnavailable(
            "OPENAI_API_KEY is empty or unset, so REAL's llm_boolean evals cannot be "
            "graded at all. Without it the scorable population drops from 102 to 47 "
            "and stops being comparable to the published baseline (DECISIONS entry 10)."
        )
    if info.get("model_default_error"):
        raise JudgeMisrouted(info["model_default_error"])
    if not info["is_openai"] and not allow_non_openai:
        raise JudgeMisrouted(
            f"the judge would run against {info['base_url']!r} (host {info['host']!r}), "
            f"not {OPENAI_HOST}. OpenAI() reads OPENAI_BASE_URL from the environment "
            f"(OPENAI_BASE_URL={info['OPENAI_BASE_URL_env']!r}), so a leaked value sends "
            f"REAL's judge to another provider and the score silently stops being the "
            f"one the published baseline was produced with (DECISIONS entries 9 and 10)."
        )
    return info


# --------------------------------------------------------------------------
# the ledger
# --------------------------------------------------------------------------


@dataclass
class JudgeCall:
    """One model call made inside agisdk's judge."""

    requested_model: str | None
    served_model: str | None
    base_url: str | None
    host: str | None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    latency_s: float = 0.0
    reply: str = ""
    error: str | None = None


@dataclass
class LlmEval:
    """One `llm_boolean` criterion, as the judge graded it."""

    rubric: str = ""
    model_response: str = ""
    similarity: float | None = None
    is_correct: bool | None = None
    error: str | None = None


@dataclass
class JudgeLedger:
    """Everything one episode's judging did. Written into the episode record."""

    installed: bool = False
    endpoint: dict = field(default_factory=dict)
    #: How many times agisdk's evaluator ran at all. Zero means the agent never
    #: sent a message, so `validate()` short-circuited and no eval of any kind
    #: was executed — a zero reward that the judge never saw.
    evaluate_calls: int = 0
    llm_evals: list[LlmEval] = field(default_factory=list)
    calls: list[JudgeCall] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def prompt_tokens(self) -> int:
        return sum(c.prompt_tokens for c in self.calls)

    @property
    def completion_tokens(self) -> int:
        return sum(c.completion_tokens for c in self.calls)

    @property
    def total_tokens(self) -> int:
        return sum(c.total_tokens for c in self.calls)

    def to_dict(self) -> dict:
        return {
            "installed": self.installed,
            "endpoint": dict(self.endpoint),
            "evaluate_calls": self.evaluate_calls,
            "judge_calls": len(self.calls),
            "llm_evals": [asdict(e) for e in self.llm_evals],
            "calls": [asdict(c) for c in self.calls],
            "errors": list(self.errors),
            "tokens": {
                "prompt": self.prompt_tokens,
                "completion": self.completion_tokens,
                "cached_prompt": sum(c.cached_tokens for c in self.calls),
                "total": self.total_tokens,
            },
        }


def usd(prompt_tokens: int, completion_tokens: int, cached_tokens: int = 0) -> float:
    """Judge cost in dollars: the published rate times measured tokens.

    No estimate is involved on either side — the rate is published (see
    `PRICE_SOURCE`) and the tokens come from the provider's own `usage`. Cached
    prompt tokens are billed at the cached rate and are subtracted from the
    uncached ones rather than double-counted.
    """
    cached = max(0, min(cached_tokens, prompt_tokens))
    fresh = prompt_tokens - cached
    return (
        fresh * GPT_41_USD_PER_1M["input"]
        + cached * GPT_41_USD_PER_1M["cached_input"]
        + completion_tokens * GPT_41_USD_PER_1M["output"]
    ) / 1_000_000


# --------------------------------------------------------------------------
# instrumentation
# --------------------------------------------------------------------------

_LEDGER = JudgeLedger()
_INSIDE = threading.local()
_ORIGINALS: dict = {}


def ledger() -> JudgeLedger:
    return _LEDGER


def reset() -> JudgeLedger:
    """Start a fresh ledger. One episode per process, so this is per-episode."""
    global _LEDGER
    _LEDGER = JudgeLedger()
    return _LEDGER


def _inside() -> bool:
    return getattr(_INSIDE, "active", False)


def install(*, endpoint_info: dict | None = None) -> JudgeLedger:
    """Patch agisdk's judge so every call it makes is recorded. Idempotent.

    Three patches, none of which changes what agisdk computes:

    * `evaluate.generate_from_model` — wrapped to mark the window. The original
      still runs, so the client, the prompt and the model are all agisdk's.
    * `Completions.create` — records any call made inside that window. This is
      where the *real* base URL comes from: `self._client.base_url` on the
      client the SDK actually built.
    * `WebCloneEvaluator.evaluate_with_llm` / `evaluate` — record the grade and
      the fact that evaluation happened at all.

    `evaluate.generate_from_model` and not `utils.generate_from_model`:
    `evaluate.py` did `from ... utils import generate_from_model`, so it holds
    its own reference and patching `utils` would patch a name nobody calls. That
    is the shape of the "instrumented, and silently measuring nothing" bug this
    module is supposed to prevent, so it is named here.
    """
    from agisdk.REAL.browsergym.webclones import evaluate as evaluate_module
    from openai.resources.chat.completions import Completions

    _LEDGER.endpoint = dict(endpoint_info) if endpoint_info is not None else endpoint()
    if _ORIGINALS:
        _LEDGER.installed = True
        return _LEDGER

    _ORIGINALS["generate_from_model"] = evaluate_module.generate_from_model
    _ORIGINALS["create"] = Completions.create
    _ORIGINALS["evaluate_with_llm"] = evaluate_module.WebCloneEvaluator.evaluate_with_llm
    _ORIGINALS["evaluate"] = evaluate_module.WebCloneEvaluator.evaluate

    def generate_from_model(*args, **kwargs):
        previous = _inside()
        _INSIDE.active = True
        try:
            return _ORIGINALS["generate_from_model"](*args, **kwargs)
        finally:
            _INSIDE.active = previous

    def create(self, *args, **kwargs):
        # The agent's own calls go through this same method in this same
        # process. Only calls made inside the judge window are the judge's.
        if not _inside():
            return _ORIGINALS["create"](self, *args, **kwargs)
        started = time.monotonic()
        call = JudgeCall(
            requested_model=kwargs.get("model"),
            served_model=None,
            base_url=str(getattr(self._client, "base_url", "")) or None,
            host=None,
        )
        call.host = urlsplit(call.base_url).hostname if call.base_url else None
        try:
            response = _ORIGINALS["create"](self, *args, **kwargs)
        except Exception as exc:
            call.error = f"{type(exc).__name__}: {exc}"
            call.latency_s = time.monotonic() - started
            _LEDGER.calls.append(call)
            _LEDGER.errors.append(call.error)
            raise
        call.latency_s = time.monotonic() - started
        call.served_model = getattr(response, "model", None)
        usage = getattr(response, "usage", None)
        if usage is not None:
            call.prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
            call.completion_tokens = getattr(usage, "completion_tokens", 0) or 0
            call.total_tokens = getattr(usage, "total_tokens", 0) or 0
            details = getattr(usage, "prompt_tokens_details", None)
            call.cached_tokens = (getattr(details, "cached_tokens", 0) or 0) if details else 0
        try:
            call.reply = (response.choices[0].message.content or "")[:200]
        except (AttributeError, IndexError):
            call.reply = ""
        _LEDGER.calls.append(call)
        return response

    def evaluate_with_llm(self, model_response, rubric, threshold=0.8):
        entry = LlmEval(rubric=rubric or "", model_response=(model_response or "")[:2000])
        _LEDGER.llm_evals.append(entry)
        try:
            is_correct, info = _ORIGINALS["evaluate_with_llm"](
                self, model_response, rubric, threshold
            )
        except Exception as exc:
            entry.error = f"{type(exc).__name__}: {exc}"
            _LEDGER.errors.append(entry.error)
            raise
        entry.is_correct = bool(is_correct)
        entry.similarity = info.get("similarity")
        return is_correct, info

    def evaluate(self, env_state=None, model_response=None):
        _LEDGER.evaluate_calls += 1
        return _ORIGINALS["evaluate"](self, env_state, model_response)

    evaluate_module.generate_from_model = generate_from_model
    Completions.create = create
    evaluate_module.WebCloneEvaluator.evaluate_with_llm = evaluate_with_llm
    evaluate_module.WebCloneEvaluator.evaluate = evaluate
    _LEDGER.installed = True
    return _LEDGER


def uninstall() -> None:
    """Put agisdk and the openai SDK back. Used by the tests, not by a run."""
    if not _ORIGINALS:
        return
    from agisdk.REAL.browsergym.webclones import evaluate as evaluate_module
    from openai.resources.chat.completions import Completions

    evaluate_module.generate_from_model = _ORIGINALS["generate_from_model"]
    Completions.create = _ORIGINALS["create"]
    evaluate_module.WebCloneEvaluator.evaluate_with_llm = _ORIGINALS["evaluate_with_llm"]
    evaluate_module.WebCloneEvaluator.evaluate = _ORIGINALS["evaluate"]
    _ORIGINALS.clear()
    _LEDGER.installed = False
