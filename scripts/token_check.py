"""How tokens are counted here, checked against the model's own count.

Run:  uv run python scripts/token_check.py [fixture ...]

The budget in `observation.py` is stated in local `tiktoken` tokens. GLM does not
use tiktoken and z.ai publishes no tokenizer for `glm-4.6`, so that budget is an
approximation of what the provider will bill — and an unchecked approximation is
just a guess with a library behind it. This script measures the disagreement.

Method: for one serialized observation, send two real chat completions that are
byte-identical apart from the observation text, and difference their
`prompt_tokens`. The framing (system message, role wrappers, chat template) is
identical in both calls, so the difference is GLM's own token count of exactly
the text the serializer produced. `max_tokens=1` keeps the completion side
irrelevant.

This is deliberately NOT the same thing as feat-001's 20 931 figure. That number
came from z.ai's `usage` field summed over a whole episode — every prompt, every
completion, all nine steps. It is not, and was never, a local count of one
observation.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from web_agent_eval import fixtures, glm
from web_agent_eval.observation import LEVELS, serialize
from web_agent_eval.tokens import count_tokens

ENCODINGS = ["cl100k_base", "o200k_base"]
SYSTEM = "You count tokens."
BASELINE = "."


def glm_prompt_tokens(client, content: str) -> int:
    response = client.chat.completions.create(
        model=glm.DEFAULT_MODEL,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}],
        max_tokens=1,
        temperature=0.0,
        extra_body={"thinking": {"type": "disabled"}},
    )
    return response.usage.prompt_tokens


def main() -> None:
    names = sys.argv[1:] or fixtures.fixture_names()
    client = glm.make_client()

    base = glm_prompt_tokens(client, BASELINE)
    print(f"model            : {glm.DEFAULT_MODEL} via {client.base_url}")
    print(f"framing baseline : prompt_tokens={base} for the fixed system message "
          f"plus {BASELINE!r}")
    print(f"local baseline   : {count_tokens(BASELINE)} ({ENCODINGS[0]}) for {BASELINE!r}")
    print()
    header = (f"{'fixture':26} {'level':5} {'cl100k':>8} {'o200k':>8} {'glm':>8} "
              f"{'glm/cl100k':>11} {'glm/o200k':>10}")
    print(header)
    print("-" * len(header))

    totals = {"cl100k_base": 0, "o200k_base": 0, "glm": 0}
    for name in names:
        obs = fixtures.load_observation(name)
        for level in LEVELS:
            text = serialize(obs, level).text
            local = {enc: count_tokens(text, enc) for enc in ENCODINGS}
            glm_tokens = glm_prompt_tokens(client, BASELINE + "\n" + text) - base
            # BASELINE + "\n" adds a token or two of its own; charge it to the
            # measurement rather than pretending it is free.
            for enc in ENCODINGS:
                totals[enc] += local[enc]
            totals["glm"] += glm_tokens
            print(f"{name:26} {level:5} {local['cl100k_base']:8,} {local['o200k_base']:8,} "
                  f"{glm_tokens:8,} {glm_tokens / max(local['cl100k_base'], 1):11.3f} "
                  f"{glm_tokens / max(local['o200k_base'], 1):10.3f}")

    print("-" * len(header))
    print(f"{'TOTAL':26} {'':5} {totals['cl100k_base']:8,} {totals['o200k_base']:8,} "
          f"{totals['glm']:8,} {totals['glm'] / max(totals['cl100k_base'], 1):11.3f} "
          f"{totals['glm'] / max(totals['o200k_base'], 1):10.3f}")
    print()
    print("ratio > 1 means the local count UNDERSTATES what z.ai bills, and a budget")
    print("stated in local tokens is that much looser than it looks.")


if __name__ == "__main__":
    main()
