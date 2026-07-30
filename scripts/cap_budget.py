"""Where feat-003's cap values come from. Offline: no browser, no network.

Run:  uv run python scripts/cap_budget.py

The token cap is the one of the three that had to be derived rather than
decided, because it is not only a safety bound. docs/DECISIONS.md entry 9
measured reasoning spend scaling with the token cap, which makes this number an
input to claim 2 — tokens per task — and it is held constant across every arm of
feat-006 and feat-007.

The requirement it has to satisfy: **never bite on an honest episode.** A cap
that fires on the rich arm and not the lean one would truncate one side of
feat-007's ablation and turn it into a comparison of two different experiments.
So it is derived from the worst case the serializer can actually produce, with
headroom, rather than tuned down to look frugal.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agisdk.REAL.browsergym.core.action.highlevel import HighLevelActionSet

from web_agent_eval import fixtures
from web_agent_eval.caps import (
    DEFAULT_MAX_STEPS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MAX_WALL_CLOCK_S,
)
from web_agent_eval.observation import (
    LEVELS,
    MEASURED_LOCAL_UNDERCOUNT,
    PROVIDER_TOKEN_BUDGET,
    TOKEN_BUDGET,
    serialize,
)
from web_agent_eval.policy import DEFAULT_MAX_REPLY_TOKENS, SYSTEM_PROMPT
from web_agent_eval.tokens import count_tokens, encoding_name

# Real actions, in the shape the gate's own trace recorded them.
SAMPLE_ACTIONS = [
    "click('209')",
    "fill('a1274', 'San Francisco')",
    "select_option('1940', 'Any week')",
    "send_msg_to_user('The first email in the Inbox has been marked as read.')",
]


def rule(text: str) -> None:
    print(f"\n{'=' * 72}\n{text}\n{'=' * 72}")


action_set = HighLevelActionSet(
    subsets=["chat", "bid", "infeas"], strict=False, multiaction=False, demo_mode="off"
)

rule("What one step costs, at worst")
print(f"local encoding            : {encoding_name()}")

system = count_tokens(SYSTEM_PROMPT)
actions = count_tokens(action_set.describe(with_long_description=False, with_examples=True))
per_action = max(count_tokens(a) for a in SAMPLE_ACTIONS)
history = per_action * DEFAULT_MAX_STEPS + count_tokens("# Actions already taken\n")
framing = count_tokens("\n\n# Action space\n\n\n# Next action\n\n")

print(f"system prompt             : {system:>7,}  local tokens")
print(f"action space description  : {actions:>7,}  short form, with examples")
print(f"history at the last step  : {history:>7,}  {DEFAULT_MAX_STEPS} x {per_action} "
      f"(longest sampled action)")
print(f"section framing           : {framing:>7,}")
print(f"observation ceiling       : {TOKEN_BUDGET:>7,}  feat-002's local budget "
      f"({PROVIDER_TOKEN_BUDGET:,} provider-side)")

print("\nlargest observation actually measured, per level:")
for level in sorted(LEVELS):
    worst_name, worst = "", 0
    for name in fixtures.fixture_names():
        spent = serialize(fixtures.load_observation(name, with_screenshot=False), level).tokens
        if spent > worst:
            worst_name, worst = name, spent
    print(f"  {level:<5} {worst:>7,}  ({worst_name})")

prompt_local = system + actions + history + framing + TOKEN_BUDGET
prompt_provider = int(prompt_local * MEASURED_LOCAL_UNDERCOUNT) + 1
step_provider = prompt_provider + DEFAULT_MAX_REPLY_TOKENS

rule("From one step to the cap")
print(f"worst prompt, local       : {prompt_local:>9,}")
print(f"  x {MEASURED_LOCAL_UNDERCOUNT} (entry 6's worst-case undercount)")
print(f"worst prompt, provider    : {prompt_provider:>9,}")
print(f"+ completion cap          : {DEFAULT_MAX_REPLY_TOKENS:>9,}  (thinking disabled, entry 4)")
print(f"worst step, provider      : {step_provider:>9,}")
print(f"x max_steps               : {DEFAULT_MAX_STEPS:>9,}")
worst_episode = step_provider * DEFAULT_MAX_STEPS
print(f"worst honest episode      : {worst_episode:>9,}  provider tokens")
print(f"\nDEFAULT_MAX_TOKENS        : {DEFAULT_MAX_TOKENS:>9,}")
headroom = DEFAULT_MAX_TOKENS / worst_episode
print(f"headroom over the worst   : {headroom:>9.2f}x")
verdict = "OK — cannot bite on an honest episode" if headroom >= 1.0 else \
          "TOO TIGHT — would truncate the rich arm and confound feat-007"
print(f"verdict                   : {verdict}")

rule("The other two, which are decisions rather than derivations")
print(f"DEFAULT_MAX_STEPS         : {DEFAULT_MAX_STEPS:>9,}    agisdk's harness default; the "
      f"gate's successful episode took 9 (entry 4)")
print(f"DEFAULT_MAX_WALL_CLOCK_S  : {DEFAULT_MAX_WALL_CLOCK_S:>9,.0f}    gate episode 35.4 s / 9 "
      f"calls; site round trips 0.13-2.37 s (entries 4, 5)")
print(f"{'':>28}    ~3x the expected worst case, and far inside the "
      f"nine-minute hang it exists to prevent")

if headroom < 1.0:
    sys.exit(1)
