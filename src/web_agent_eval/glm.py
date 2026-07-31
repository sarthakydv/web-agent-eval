"""The z.ai GLM client.

z.ai exposes two OpenAI-compatible base URLs and they are NOT interchangeable.
The key in `.env` is a GLM Coding Plan key, and a coding-plan key is rejected by
the pay-as-you-go endpoint with HTTP 429 / code 1113 "Insufficient balance".
Measured, not inferred — see docs/DECISIONS.md entry 4.

  https://api.z.ai/api/paas/v4/           pay-as-you-go   -> 429 with this key
  https://api.z.ai/api/coding/paas/v4/    coding plan     -> 200 with this key
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime

from openai import OpenAI

CODING_PLAN_BASE_URL = "https://api.z.ai/api/coding/paas/v4/"
PAYG_BASE_URL = "https://api.z.ai/api/paas/v4/"

DEFAULT_MODEL = "glm-4.6"


def base_url() -> str:
    """The base URL to drive GLM through. Overridable, defaults to the coding plan."""
    return os.environ.get("ZAI_BASE_URL", CODING_PLAN_BASE_URL)


def served_model(model: str = DEFAULT_MODEL) -> dict:
    """What the endpoint actually serves when this project asks for `model`.

    The requested string and the served string are not the same fact. Entry 9
    refused `glm-5.1` because `glm-5.2` answered to it, with no way to pin the
    one that was asked for; entry 13 kept `gpt-4.1-2025-04-14` in every judge
    record for the same reason. A run's manifest records the requested model
    because that is what was asked for, and this records what answered — so a
    rerun served by something else is a changed value rather than a silent
    change of subject.

    One trivial completion. It is a real call, so it is also the last cheap
    proof that the key works before an hours-long run starts on it.
    """
    client = make_client()
    started = time.monotonic()
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "ok"}],
        max_tokens=1,
        temperature=0.0,
    )
    return {
        "requested": model,
        "served": getattr(response, "model", None),
        "base_url": base_url(),
        "latency_s": round(time.monotonic() - started, 3),
        "probed_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def make_client() -> OpenAI:
    """An OpenAI-SDK client pointed at z.ai.

    This is the whole answer to feat-001's question 1: the model is reached
    through the stock `openai` SDK with a custom `base_url`, so anything that
    accepts an OpenAI-compatible client accepts GLM.
    """
    key = os.environ.get("ZAI_API_KEY")
    if not key:
        raise RuntimeError("ZAI_API_KEY is not set — put it in .env")
    return OpenAI(api_key=key, base_url=base_url())
