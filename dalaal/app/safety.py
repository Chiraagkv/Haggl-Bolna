"""Guards that run before any real call is placed (a small piece of ticket #18, needed now).

The full cost ceiling, daily cap and one-live-order lock arrive in Phase 2. Until then, no script
may dial a number that is not on the verified list, or while the kill switch is on.
"""

import re

from app.config import Settings

_E164 = re.compile(r"^\+[1-9]\d{6,14}$")


class DialRefused(RuntimeError):
    pass


def check_can_dial(number: str, settings: Settings) -> None:
    """Raise DialRefused unless it is safe to place this call."""
    if settings.kill_switch:
        raise DialRefused("KILL_SWITCH is on: no calls will be placed.")
    if not _E164.match(number or ""):
        raise DialRefused(f"{number!r} is not an E.164 number (example: +919876543210).")
    if not settings.require_verified_numbers:
        return
    verified = settings.verified_number_set
    if not verified:
        raise DialRefused(
            "VERIFIED_NUMBERS is empty. Add your teammates' verified numbers to .env so tests can "
            "never reach a real supplier by accident."
        )
    if number not in verified:
        raise DialRefused(f"{number} is not in VERIFIED_NUMBERS. Only teammates may be dialed during testing.")
