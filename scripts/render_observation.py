"""Render the committed observations at every richness level. Offline.

Run:  uv run python scripts/render_observation.py            # the token table
      uv run python scripts/render_observation.py <fixture> <level>   # the text

No browser, no network, no API key — it reads the fixtures under
`fixtures/observations/` and prints what the model would have been shown.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from web_agent_eval import fixtures
from web_agent_eval.observation import (
    LEVELS,
    PROVIDER_TOKEN_BUDGET,
    TOKEN_BUDGET,
    serialize,
)
from web_agent_eval.tokens import encoding_name


def table() -> None:
    print(f"local budget    : {TOKEN_BUDGET:,} tokens ({encoding_name()})")
    print(f"provider claim  : {PROVIDER_TOKEN_BUDGET:,} tokens as z.ai counts them")
    for level in LEVELS.values():
        print(f"level {level.name:5}   : {level.describe()}")
    print()
    header = f"{'fixture':26} {'level':6} {'tokens':>7} {'budget':>7} {'ok':>4}  truncated"
    print(header)
    print("-" * len(header))
    for name in fixtures.fixture_names():
        obs = fixtures.load_observation(name)
        for level in LEVELS:
            result = serialize(obs, level)
            cut = ", ".join(f"{k} -{v} lines" for k, v in result.truncated.items()) or "-"
            print(f"{name:26} {result.level:6} {result.tokens:7,} {result.budget:7,} "
                  f"{result.within_budget!s:>4}  {cut}")


def main() -> None:
    if len(sys.argv) < 2:
        table()
        return
    name = sys.argv[1]
    level = sys.argv[2] if len(sys.argv) > 2 else "lean"
    result = serialize(fixtures.load_observation(name), level)
    print(f"--- {name} @ {result.level}: {result.tokens:,} tokens "
          f"(budget {result.budget:,}, truncated={result.truncated or 'nothing'}) ---\n")
    print(result.text)


if __name__ == "__main__":
    main()
