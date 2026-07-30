"""Pulling one action out of the model's reply.

Moved here from `gate_agent.py`, unchanged. It was written for `feat-001`'s
gate but it is not gate scaffolding: docs/DECISIONS.md entry 4 records that
`feat-003` inherits the finding, and entry 6 records that it lives "on the
action side" rather than in the serializer. The loop needs it, `gate_agent`
still imports it from here, and `tests/test_gate_agent.py` covers it with the
strings that really broke the first run.
"""

from __future__ import annotations

import re

from agisdk.REAL.browsergym.core.action.parsers import highlevel_action_parser

_FENCE = re.compile(r"```(?:python)?\s*(.+?)\s*```", re.DOTALL)


def extract_action(text: str) -> str:
    """Pull exactly one action call out of the model's narration.

    Handing browsergym the raw reply does not work, and the failure is not
    obvious. Its parser scans the WHOLE string, pyparsing skips whitespace, and
    a second match is rejected as a multi-action — so ordinary English prose
    parses as a function call:

        "The first email's checkbox is already checked (checked='true')."
                                              -> checked('true')
        'I am viewing the first email ("Your Account Statement is Ready")'
                                              -> email('Your Account Statement is Ready')

    Both of those really did abort a step in the first gate run. The last call
    in the reply is the intended action; everything before it is prose.
    """
    fenced = _FENCE.findall(text)
    candidate = fenced[-1] if fenced else text
    calls = [call for match in highlevel_action_parser.search_string(candidate).as_list()
             for call in match]
    if not calls:
        return candidate.strip()
    name, args = calls[-1]
    return f"{name}(" + ", ".join(repr(arg) for arg in args) + ")"
