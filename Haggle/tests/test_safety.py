import pytest

from app.config import Settings
from app.safety import DialRefused, check_can_dial

GOOD = "+919876543210"


def settings(**kw):
    return Settings(_env_file=None, **kw)


def test_verified_number_is_allowed():
    check_can_dial(GOOD, settings(verified_numbers=f"{GOOD}, +911111111111"))


def test_unverified_number_is_refused():
    with pytest.raises(DialRefused, match="not in VERIFIED_NUMBERS"):
        check_can_dial("+911111111112", settings(verified_numbers=GOOD))


def test_empty_verified_list_refuses_everything():
    with pytest.raises(DialRefused, match="empty"):
        check_can_dial(GOOD, settings())


def test_kill_switch_wins_even_for_verified_numbers():
    with pytest.raises(DialRefused, match="KILL_SWITCH"):
        check_can_dial(GOOD, settings(verified_numbers=GOOD, kill_switch=True))


@pytest.mark.parametrize("bad", ["9876543210", "+0123", "", "+91 98765 43210", "abc"])
def test_malformed_numbers_are_refused(bad):
    with pytest.raises(DialRefused):
        check_can_dial(bad, settings(verified_numbers=bad))
