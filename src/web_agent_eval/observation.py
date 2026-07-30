"""Observation -> text. One direction, and richness is a parameter.

This is everything the model gets to see about the page. It takes a raw agisdk
observation — the CDP DOM snapshot, the merged accessibility tree, the extracted
element properties, the screenshot — and renders it as the text that goes into
the prompt.

**Richness is a parameter, not a choice made here.** `feat-007`'s ablation varies
exactly this and nothing else, so the seam has to exist before the ablation does;
bolting one on afterwards is how an ablation ends up comparing two things at
once. A `Richness` is a data object, `serialize()` takes one, and the two shipped
levels differ only in the fields of that object.

What the levels do NOT vary: the goal, the URL and the error from the last
action appear at every level. Dropping those does not make an observation
poorer — it changes the task the agent is being given, and it would confound
the very ablation this seam exists for.

Budget: every level is rendered under `TOKEN_BUDGET` local tokens, enforced by
truncation rather than by hope. See `tokens.py` for what "local token" means and
where it disagrees with the provider's own count.

Scope: this module renders. It does not call a model, does not choose an action,
does not retry and does not cap an episode — those are `feat-003`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agisdk.REAL.browsergym.utils.obs import (
    flatten_axtree_to_str,
    flatten_dom_to_str,
    prune_html,
)

from web_agent_eval.tokens import count_tokens, truncate_to_tokens

# The budget, and why there are two numbers for it.
#
# The claim is provider-side: no observation exceeds 12 000 tokens *as z.ai
# counts them*. Enforcement has to be local — a unit test cannot bill an API
# call — and the local tokenizer is not GLM's. `scripts/token_check.py` measured
# the gap on all ten fixture/level pairs: `cl100k_base` understates z.ai's own
# `prompt_tokens` by at most 2.2%. So the local ceiling is the provider ceiling
# divided by that worst case, and the margin is a measurement rather than a
# guess. docs/DECISIONS.md entry 6 has the table.
#
# 12 000 itself is a measured choice too: across the five committed fixtures the
# richest accessibility tree tops out near 11 000 tokens before any HTML is
# added, and the leanest sits near 2 000. A budget much under that would truncate
# the rich arm on every page and turn feat-007 into a comparison of two
# truncations.
#
# This bounds THIS block only. The action space description, the step history
# and the system prompt are added by the loop (feat-003) and counted separately.
PROVIDER_TOKEN_BUDGET = 12_000
MEASURED_LOCAL_UNDERCOUNT = 1.022
TOKEN_BUDGET = int(PROVIDER_TOKEN_BUDGET / MEASURED_LOCAL_UNDERCOUNT)  # 11 741


@dataclass(frozen=True)
class Richness:
    """One rung of observation richness. The ablation varies this object alone."""

    name: str
    #: keyword arguments handed to browsergym's `flatten_axtree_to_str`
    axtree_options: dict = field(default_factory=dict)
    #: include a pruned HTML rendering of the DOM snapshot
    include_html: bool = False
    #: include open tabs and the focused element
    include_page_context: bool = False
    #: mention the screenshot (dimensions only — see `_screenshot_note`)
    include_screenshot_note: bool = False
    #: share of the content budget each content section may claim, in order.
    #: Unclaimed allowance rolls forward to the next section.
    weights: dict = field(default_factory=lambda: {"axtree": 1.0})

    def describe(self) -> str:
        bits = [f"axtree({', '.join(f'{k}={v}' for k, v in sorted(self.axtree_options.items())) or 'defaults'})"]
        if self.include_html:
            bits.append("pruned-html")
        if self.include_page_context:
            bits.append("page-context")
        if self.include_screenshot_note:
            bits.append("screenshot-note")
        return f"{self.name}: " + " + ".join(bits)


#: Interactive elements only: visible nodes that carry a bid, no annotations, no
#: HTML. This is close to what the gate agent sent, and it is the cheap arm.
LEAN = Richness(
    name="lean",
    axtree_options={
        "filter_visible_only": True,
        "filter_with_bid_only": True,
        "skip_generic": True,
    },
    weights={"axtree": 1.0},
)

#: Every visible node — including the static text a bid-only filter throws away —
#: annotated with visibility, clickability and centre coordinates, followed by a
#: pruned HTML view of the same page. The expensive arm.
RICH = Richness(
    name="rich",
    axtree_options={
        "filter_visible_only": True,
        "skip_generic": True,
        "with_visible": True,
        "with_clickable": True,
        "with_center_coords": True,
    },
    include_html=True,
    include_page_context=True,
    include_screenshot_note=True,
    weights={"axtree": 0.65, "html": 0.35},
)

LEVELS: dict[str, Richness] = {level.name: level for level in (LEAN, RICH)}


def level_by_name(name: str) -> Richness:
    try:
        return LEVELS[name]
    except KeyError:
        raise ValueError(f"unknown richness level {name!r}; have {sorted(LEVELS)}") from None


@dataclass(frozen=True)
class Serialized:
    """The rendered observation, plus what it cost and what was cut to fit."""

    text: str
    level: str
    tokens: int
    budget: int
    #: section name -> lines dropped to fit the budget. Empty means nothing was cut.
    truncated: dict[str, int] = field(default_factory=dict)
    #: True if the whole block had to be clamped after section budgeting — only
    #: reachable when the fixed sections alone exceed the budget.
    hard_clamped: bool = False

    @property
    def within_budget(self) -> bool:
        return self.tokens <= self.budget


# --------------------------------------------------------------------------
# section rendering
# --------------------------------------------------------------------------


def _goal(obs: dict) -> str:
    goal = obs.get("goal")
    if goal:
        return str(goal)
    parts = []
    for message in obs.get("goal_object") or []:
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                parts.extend(c.get("text", "") for c in content if isinstance(c, dict))
        else:
            parts.append(str(message))
    return "\n".join(p for p in parts if p).strip()


def _axtree(obs: dict, level: Richness) -> str:
    """Flatten the accessibility tree at this level's richness.

    Falls back to a pre-flattened `axtree_txt` when the raw tree is gone —
    agisdk's `default_obs_preprocessor` deletes `axtree_object`, and an agent
    that uses it would otherwise silently render nothing. The fallback cannot
    honour the level's options, so it says so.
    """
    tree = obs.get("axtree_object")
    if tree is None:
        pre = obs.get("axtree_txt")
        if not pre:
            return ""
        return ("(pre-flattened tree: axtree_object was dropped upstream, so this "
                f"level's options were not applied)\n{pre}")
    return flatten_axtree_to_str(
        tree,
        extra_properties=obs.get("extra_element_properties"),
        **level.axtree_options,
    )


def _html(obs: dict) -> str:
    dom = obs.get("dom_object")
    if dom is None:
        return obs.get("pruned_html") or ""
    return prune_html(
        flatten_dom_to_str(
            dom,
            extra_properties=obs.get("extra_element_properties"),
            filter_visible_only=True,
        )
    )


def _screenshot_note(obs: dict) -> str:
    """What the screenshot contributes, stated plainly: its dimensions.

    `glm-4.6` through z.ai's coding plan is text-only, so no pixels are sent.
    The screenshot is captured and stored regardless — it is part of the
    observation, and a vision model would use it — but pretending it informs
    this text would be a lie about what the model sees.
    """
    shot = obs.get("screenshot")
    shape = getattr(shot, "shape", None)
    if shape is None:
        return "no screenshot in this observation"
    height, width = shape[0], shape[1]
    return (f"{width}x{height} screenshot captured and stored, but not sent: "
            f"glm-4.6 via z.ai is text-only. No pixel information reached the model.")


def _page_context(obs: dict) -> str:
    lines = []
    tabs = obs.get("open_pages_urls") or []
    if tabs:
        lines.append("open tabs: " + ", ".join(str(t) for t in tabs))
    focused = obs.get("focused_element_bid")
    if focused:
        lines.append(f"focused element: [{focused}]")
    return "\n".join(lines)


def _last_action(obs: dict) -> str:
    lines = []
    if obs.get("last_action"):
        lines.append(f"action: {obs['last_action']}")
    if obs.get("last_action_error"):
        lines.append(f"error: {obs['last_action_error'].strip()}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# budgeting
# --------------------------------------------------------------------------


def _fit_lines(text: str, budget: int) -> tuple[str, int]:
    """Keep as many leading lines as fit in `budget` tokens. Returns (text, dropped).

    Line-wise so the result is still a readable tree rather than a sentence cut
    mid-token, and binary search so a 40 000-token page costs ~15 counts.
    """
    if count_tokens(text) <= budget:
        return text, 0
    lines = text.splitlines()
    low, high = 0, len(lines)
    while low < high:
        mid = (low + high + 1) // 2
        if count_tokens("\n".join(lines[:mid])) <= budget:
            low = mid
        else:
            high = mid - 1
    kept = "\n".join(lines[:low])
    dropped = len(lines) - low
    marker = f"\n[... {dropped} of {len(lines)} lines dropped to fit the token budget]"
    if count_tokens(kept + marker) > budget and low > 0:
        kept = "\n".join(lines[: low - 1])
        dropped += 1
        marker = f"\n[... {dropped} of {len(lines)} lines dropped to fit the token budget]"
    return kept + marker, dropped


def serialize(
    obs: dict,
    level: Richness | str = LEAN,
    *,
    budget: int = TOKEN_BUDGET,
) -> Serialized:
    """Render `obs` as the text the model sees, at `level`, under `budget` tokens."""
    if isinstance(level, str):
        level = level_by_name(level)

    # Present at every level: removing these changes the task, not the richness.
    fixed: list[tuple[str, str]] = [
        ("Goal", _goal(obs)),
        ("Current URL", str(obs.get("url") or "")),
    ]
    last = _last_action(obs)
    if last:
        fixed.append(("Last action", last))
    if level.include_page_context:
        context = _page_context(obs)
        if context:
            fixed.append(("Page context", context))
    if level.include_screenshot_note:
        fixed.append(("Screenshot", _screenshot_note(obs)))

    def render(sections: list[tuple[str, str]]) -> str:
        return "\n\n".join(f"# {title}\n{body}" for title, body in sections if body)

    fixed_text = render(fixed)
    # Each content section costs its own header too; charge for it up front.
    header_cost = sum(count_tokens(f"\n\n# {t}\n") for t in ("Page", "Page HTML"))
    remaining = budget - count_tokens(fixed_text) - header_cost

    bodies = {"axtree": _axtree(obs, level)}
    if level.include_html:
        bodies["html"] = _html(obs)

    content: list[tuple[str, str]] = []
    truncated: dict[str, int] = {}
    titles = {"axtree": "Page", "html": "Page HTML"}
    content_budget = remaining
    names = list(level.weights)
    for index, name in enumerate(names):
        body = bodies.get(name) or ""
        if not body:
            continue
        # Weights are shares of the whole content budget, and whatever an earlier
        # section leaves unclaimed rolls forward — so the last section is handed
        # everything that is left rather than a fraction of a fraction.
        last = index == len(names) - 1
        allowance = remaining if last else min(remaining, int(content_budget * level.weights[name]))
        fitted, dropped = _fit_lines(body, max(allowance, 0))
        if dropped:
            truncated[name] = dropped
        remaining -= count_tokens(fitted)
        content.append((titles[name], fitted))

    text = render(fixed + content)
    total = count_tokens(text)
    hard_clamped = False
    if total > budget:
        # Only reachable when the fixed sections alone blow the budget.
        text = truncate_to_tokens(text, budget)
        total = count_tokens(text)
        hard_clamped = True

    return Serialized(
        text=text,
        level=level.name,
        tokens=total,
        budget=budget,
        truncated=truncated,
        hard_clamped=hard_clamped,
    )
