"""Fault injection for the dummy services.

Faults are addressed to a run, a service and (optionally) a tool, carry a TTL or a one-shot
counter, and are installed only through the local operator CLI — never through an agent argument.
Modes are the ones the acceptance matrix needs:

``delay_before_commit``
    Hold the local transaction open before committing, to exercise a Gate deadline and cancel.
``commit_then_drop_response``
    Commit the business change, then hold the response past the Gate's upstream deadline, so the
    Gate observes a lost response while the effect exists. (An ASGI-level connection drop is not
    reachable from inside a tool handler; holding past the deadline produces the same observable
    state and is deterministic to test.)
``business_error_before_commit``
    Refuse with a typed business error and no local commit.
``malformed_result``
    Commit, then return a payload the published output schema rejects.
``oversized_result``
    Commit, then return a payload larger than the result limit the Gate accepts.
"""
MODES = ('delay_before_commit', 'commit_then_drop_response', 'business_error_before_commit',
         'malformed_result', 'oversized_result')

HOLD_SECONDS = 7.0
OVERSIZED_PADDING = 512 * 1024 + 4096
