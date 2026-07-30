"""The observation serializer, over real captured observations. No browser.

Every fixture here came off a live agisdk run against the hosted replica sites
(`scripts/capture_observations.py`) and is committed under
`fixtures/observations/`: the full CDP DOM snapshot, the merged accessibility
tree, the extracted element properties and the PNG screenshot, exactly as
browsergym handed them over. Nothing below was written by hand, which is the
point — a serializer tested against a hand-written page tests the hand-written
page.

These tests read files and count tokens. They start no browser and make no
network call.
"""

import pytest

from web_agent_eval import fixtures
from web_agent_eval.observation import (
    LEAN,
    LEVELS,
    RICH,
    TOKEN_BUDGET,
    Richness,
    level_by_name,
    serialize,
)

NAMES = fixtures.fixture_names()

# A page that had actually finished loading. gomail step00 is a real capture of
# a page mid-load (13 accessibility nodes), kept deliberately as the degenerate
# case, but it is useless for "is rich richer than lean".
LOADED = "v1.gomail-2_step02"


def test_the_fixtures_are_actually_there():
    # Guards against a green suite that silently tested nothing.
    assert len(NAMES) >= 4, NAMES
    assert LOADED in NAMES


@pytest.fixture(scope="module")
def loaded():
    return fixtures.load_observation(LOADED)


# --------------------------------------------------------------------------
# the budget
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("level", sorted(LEVELS))
def test_every_fixture_renders_under_the_token_budget(name, level):
    result = serialize(fixtures.load_observation(name), level)
    assert result.tokens <= TOKEN_BUDGET, f"{name}/{level} spent {result.tokens}"
    assert result.within_budget
    # A hard clamp means section budgeting failed and the text was cut mid-page.
    assert not result.hard_clamped


@pytest.mark.parametrize("level", sorted(LEVELS))
def test_a_page_too_large_for_the_budget_is_truncated_rather_than_overflowing(loaded, level):
    result = serialize(loaded, level, budget=400)
    assert result.tokens <= 400
    assert result.truncated, "a 400-token budget on a real page must drop something"
    assert "dropped to fit the token budget" in result.text


def test_truncation_reports_how_much_it_dropped(loaded):
    result = serialize(loaded, RICH, budget=1000)
    assert sum(result.truncated.values()) > 0
    for section, dropped in result.truncated.items():
        assert dropped > 0
        assert section in ("axtree", "html")


def test_a_budget_smaller_than_the_fixed_sections_still_holds(loaded):
    # Goal + URL + last action alone exceed 5 tokens, so this forces the clamp.
    result = serialize(loaded, LEAN, budget=5)
    assert result.tokens <= 5
    assert result.hard_clamped


# --------------------------------------------------------------------------
# the two levels are genuinely different
# --------------------------------------------------------------------------


def test_the_same_observation_renders_differently_at_the_two_levels(loaded):
    lean, rich = serialize(loaded, LEAN), serialize(loaded, RICH)
    assert lean.text != rich.text
    assert rich.tokens > lean.tokens * 2, (lean.tokens, rich.tokens)


def test_rich_carries_element_annotations_and_lean_does_not(loaded):
    lean, rich = serialize(loaded, LEAN).text, serialize(loaded, RICH).text
    assert 'center="(' in rich and "visible" in rich
    assert 'center="(' not in lean


def test_rich_carries_html_and_screenshot_context_and_lean_does_not(loaded):
    lean, rich = serialize(loaded, LEAN).text, serialize(loaded, RICH).text
    assert "# Page HTML" in rich and "# Screenshot" in rich and "# Page context" in rich
    assert "# Page HTML" not in lean and "# Screenshot" not in lean


def test_rich_keeps_static_text_that_leans_bid_filter_discards(loaded):
    # The bid-only filter is the main thing lean gives up: text nodes with no
    # interactive handle. If both levels kept them, the arms would be closer
    # than the ablation claims.
    lean, rich = serialize(loaded, LEAN).text, serialize(loaded, RICH).text
    assert rich.count("InlineTextBox") > 0
    assert lean.count("InlineTextBox") == 0


def test_both_levels_still_expose_the_interactive_elements(loaded):
    # Lean is cheaper, not blind: the bids an action would target survive.
    for level in (LEAN, RICH):
        text = serialize(loaded, level).text
        assert "button" in text
        assert "[" in text and "]" in text


# --------------------------------------------------------------------------
# what does NOT vary with richness
# --------------------------------------------------------------------------


@pytest.mark.parametrize("level", sorted(LEVELS))
def test_goal_and_url_are_present_at_every_level(loaded, level):
    text = serialize(loaded, level).text
    assert "# Goal" in text
    assert 'Mark the first email in the Inbox as "read".' in text
    assert "# Current URL" in text
    assert "https://evals-gomail.vercel.app/" in text


@pytest.mark.parametrize("level", sorted(LEVELS))
def test_the_last_action_error_survives_at_every_level(level):
    obs = fixtures.load_observation(LOADED)
    obs["last_action_error"] = "TimeoutError: locator.click: Timeout 5000ms exceeded"
    text = serialize(obs, level).text
    assert "TimeoutError" in text


# --------------------------------------------------------------------------
# richness is a parameter, which is the whole reason this seam exists
# --------------------------------------------------------------------------


def test_a_level_can_be_named_as_a_string(loaded):
    assert serialize(loaded, "rich").text == serialize(loaded, RICH).text
    assert level_by_name("lean") is LEAN


def test_an_unknown_level_is_refused_rather_than_defaulted():
    with pytest.raises(ValueError, match="unknown richness level"):
        level_by_name("medium")


def test_a_caller_defined_level_works_without_touching_the_serializer(loaded):
    # feat-007 varies exactly this object. If a new rung needed an edit to
    # serialize(), the ablation would be comparing a code change as well.
    coords_only = Richness(
        name="coords-only",
        axtree_options={"filter_visible_only": True, "with_center_coords": True},
    )
    result = serialize(loaded, coords_only)
    assert result.level == "coords-only"
    assert 'center="(' in result.text
    assert "# Page HTML" not in result.text
    assert result.tokens <= TOKEN_BUDGET


def test_a_level_describes_itself_for_the_record():
    assert RICH.describe().startswith("rich: axtree(")
    assert "pruned-html" in RICH.describe()
    assert "pruned-html" not in LEAN.describe()


# --------------------------------------------------------------------------
# degenerate observations
# --------------------------------------------------------------------------


def test_an_observation_mid_load_renders_without_pretending_to_have_content():
    # Real capture: the page had not finished loading, and the gate agent's
    # first two actions were noop() for exactly this reason.
    result = serialize(fixtures.load_observation("v1.gomail-2_step00"), RICH)
    assert result.tokens < 2000
    assert "# Goal" in result.text


@pytest.mark.parametrize("level", sorted(LEVELS))
def test_an_empty_observation_does_not_crash(level):
    result = serialize({}, level)
    assert isinstance(result.text, str)
    assert result.tokens <= TOKEN_BUDGET


def test_a_preprocessed_observation_falls_back_and_says_so(loaded):
    # agisdk's default_obs_preprocessor deletes axtree_object. An agent using it
    # would otherwise render an empty page and never find out.
    stripped = {k: v for k, v in loaded.items() if k not in ("axtree_object", "dom_object")}
    stripped["axtree_txt"] = "[64] main 'Main content'"
    result = serialize(stripped, RICH)
    assert "pre-flattened tree" in result.text
    assert "main 'Main content'" in result.text


def test_the_screenshot_note_reports_the_real_capture_size(loaded):
    text = serialize(loaded, RICH).text
    assert "1280x720 screenshot captured and stored, but not sent" in text


def test_an_observation_without_a_screenshot_says_that_instead():
    obs = fixtures.load_observation(LOADED, with_screenshot=False)
    assert "no screenshot in this observation" in serialize(obs, RICH).text
