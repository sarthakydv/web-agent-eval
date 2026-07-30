"""Action extraction, over the strings that actually broke the first gate run.

These are not invented cases. Both prose examples below are copied verbatim from
`runs/gate/v1.gomail-2.trace.jsonl` on 2026-07-31, where each one aborted a step
with "Received a multi-action, only single-actions are allowed." browsergym's
parser scans the whole reply and pyparsing skips whitespace, so `checked (...)`
inside an English sentence parses as a call. No browser or network needed.
"""

from web_agent_eval.gate_agent import extract_action


def test_prose_containing_a_parenthesised_assignment_does_not_become_an_action():
    reply = (
        "The first email's checkbox is already checked (checked='true'). "
        "I need to open the email to mark it as read.\n\nclick('1940')"
    )
    assert extract_action(reply) == "click('1940')"


def test_prose_containing_a_parenthesised_quote_does_not_become_an_action():
    reply = (
        'I can see that I\'m currently viewing the first email ("Your Account Statement '
        'is Ready"). I\'ll click the "Back to inbox" button.\n\nclick(\'2757\')'
    )
    assert extract_action(reply) == "click('2757')"


def test_a_fenced_block_is_preferred_over_the_narration_around_it():
    reply = "I will finish now.\n```\nsend_msg_to_user(\"done\")\n```"
    assert extract_action(reply) == "send_msg_to_user('done')"


def test_a_bare_call_with_no_fence_still_parses():
    # glm-4.6 usually omits the fence even when asked for one.
    assert extract_action("Clicking it.\n\nclick('209')") == "click('209')"


def test_a_reply_with_no_call_at_all_is_passed_through_for_the_env_to_reject():
    assert extract_action("I am not sure what to do.") == "I am not sure what to do."
