"""Local token counting, and the honest caveat attached to it.

**How tokens are counted here:** `tiktoken`, encoding `cl100k_base`, run locally
over the serialized text. That is *not* GLM's tokenizer — z.ai publishes no
tokenizer for `glm-4.6` — so every local count is an approximation of the number
the provider will bill.

The approximation was measured rather than assumed. `scripts/token_check.py`
sends a real serialized observation to z.ai and reads the `prompt_tokens` that
comes back, isolating the observation's contribution by differencing two calls
that share identical framing. The measured disagreement is recorded in
docs/DECISIONS.md entry 6, and the ratio there is what any budget stated in
local tokens must be read against.

The two numbers this project reports are therefore different things and are
never mixed:

  - **budget accounting** (this module) — local, deterministic, needs no network,
    computable on a fixture in a unit test.
  - **cost accounting** (feat-005) — the provider's `usage` field, summed from
    responses that actually happened. Never estimated locally.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path

# tiktoken fetches its BPE file once and caches it. Point that cache inside the
# repo so a cleared system temp directory does not silently turn a unit test
# into a network call.
_CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "tiktoken"
os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(_CACHE_DIR))

import tiktoken

DEFAULT_ENCODING = "cl100k_base"


def encoding_name() -> str:
    """The encoding used for budget accounting. Overridable for a comparison run."""
    return os.environ.get("WEB_AGENT_EVAL_ENCODING", DEFAULT_ENCODING)


@functools.lru_cache(maxsize=4)
def _encoder(name: str):
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return tiktoken.get_encoding(name)


def make_encoder(encoding: str | None = None):
    """A tokenizer handle for one owner to keep — the per-episode path.

    `count_tokens` goes through a process-wide `lru_cache`, which `feat-003`'s
    loop deliberately does not rely on: an episode owns its own counter so that
    three concurrent episodes share no mutable state. tiktoken keeps a registry
    of its own behind `get_encoding`, so the object handed back may still be
    shared — that is safe, and it is stated rather than glossed, because a
    `tiktoken.Encoding` is immutable and carries no per-caller state. What must
    not be shared is the *count*, and that lives on the ledger, not here.
    """
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return tiktoken.get_encoding(encoding or encoding_name())


def count_tokens(text: str, encoding: str | None = None) -> int:
    """Local token count of `text`. Approximate for GLM — see the module docstring."""
    return len(_encoder(encoding or encoding_name()).encode(text, disallowed_special=()))


def truncate_to_tokens(text: str, budget: int, encoding: str | None = None) -> str:
    """Hard clamp: cut `text` to at most `budget` tokens, on a token boundary."""
    if budget <= 0:
        return ""
    enc = _encoder(encoding or encoding_name())
    ids = enc.encode(text, disallowed_special=())
    if len(ids) <= budget:
        return text
    return enc.decode(ids[:budget])
