"""Local token counting. Offline, deterministic, and honest about what it is not.

The counts here are `tiktoken`/`cl100k_base`, not GLM's tokenizer. The gap
between the two was measured against real z.ai `prompt_tokens` in
`scripts/token_check.py` and is recorded in docs/DECISIONS.md entry 6; the last
test below is the invariant that measurement bought.
"""

from web_agent_eval.observation import (
    MEASURED_LOCAL_UNDERCOUNT,
    PROVIDER_TOKEN_BUDGET,
    TOKEN_BUDGET,
)
from web_agent_eval.tokens import count_tokens, encoding_name, truncate_to_tokens


def test_counting_is_deterministic_and_encoding_is_named():
    assert encoding_name() == "cl100k_base"
    text = "[64] main 'Main content'\n\t[73] button 'close'"
    assert count_tokens(text) == count_tokens(text) > 0


def test_truncation_never_exceeds_its_budget():
    text = "[64] main 'Main content'\n" * 500
    for budget in (0, 1, 17, 250):
        assert count_tokens(truncate_to_tokens(text, budget)) <= budget


def test_text_already_under_budget_is_returned_untouched():
    text = "click('209')"
    assert truncate_to_tokens(text, 1000) == text


def test_the_local_budget_leaves_room_for_the_measured_undercount():
    # The claim is provider-side: 12 000 tokens as z.ai counts them. The local
    # ceiling has to absorb the worst measured disagreement, or the claim is
    # only true in a unit the provider does not bill in.
    assert TOKEN_BUDGET * MEASURED_LOCAL_UNDERCOUNT <= PROVIDER_TOKEN_BUDGET
