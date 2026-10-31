"""Bolna execution statuses and their order.

Lifecycle (from Bolna's AGENTS.md):
    queued -> initiated -> ringing -> in-progress -> call-disconnected -> completed
    (or no-answer / busy / failed)

`call-disconnected` is NOT terminal: duration, cost, recording and extracted data are still
empty there and arrive with `completed` a few seconds later. We only trust data from
`completed`.
"""

TERMINAL = frozenset(
    {"completed", "no-answer", "busy", "failed", "canceled", "stopped", "error", "balance-low"}
)

_RANK = {
    "pending": -1,  # planned by us, not yet handed to Bolna
    "scheduled": 0,
    "queued": 1,
    "rescheduled": 1,
    "initiated": 2,
    "ringing": 3,
    "in-progress": 4,
    "call-disconnected": 5,
}
TERMINAL_RANK = 6


def rank(status: str | None) -> int | None:
    """Position of a status in the lifecycle, or None if we do not recognise it."""
    if status is None:
        return None
    s = status.strip().lower()
    if s in TERMINAL:
        return TERMINAL_RANK
    return _RANK.get(s)


def is_terminal(status: str | None) -> bool:
    return bool(status) and status.strip().lower() in TERMINAL
