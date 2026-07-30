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

from openai import OpenAI

CODING_PLAN_BASE_URL = "https://api.z.ai/api/coding/paas/v4/"
PAYG_BASE_URL = "https://api.z.ai/api/paas/v4/"

DEFAULT_MODEL = "glm-4.6"


def base_url() -> str:
    """The base URL to drive GLM through. Overridable, defaults to the coding plan."""
    return os.environ.get("ZAI_BASE_URL", CODING_PLAN_BASE_URL)


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
