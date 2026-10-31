import httpx
import pytest

from app.bolna_account import fetch_account, make_client, notes_snippet


def client_returning(status: int, payload: dict | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/user/me"
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(status, json=payload or {})

    return make_client("test-key", "https://api.bolna.ai", transport=httpx.MockTransport(handler))


def test_trial_account_can_run_pairs():
    c = client_returning(200, {"name": "Team", "email": "t@x.com", "wallet": 150.5, "concurrency": 2})
    info = fetch_account(c)
    assert info.concurrency == 2
    assert info.wallet == 150.5
    assert info.can_run_pairs  # round 1 dials suppliers two at a time
    assert "OK" in notes_snippet(info, "now")


def test_single_call_account_is_not_enough():
    info = fetch_account(client_returning(200, {"name": "Team", "email": "t@x.com", "wallet": 1, "concurrency": 1}))
    assert not info.can_run_pairs
    assert "NOT ENOUGH" in notes_snippet(info, "now")


def test_paid_account_can():
    c = client_returning(200, {"name": "Team", "email": "t@x.com", "wallet": 900, "concurrency": 10})
    info = fetch_account(c)
    assert info.can_run_pairs
    assert "OK" in notes_snippet(info, "now")


def test_missing_fields_do_not_crash():
    info = fetch_account(client_returning(200, {}))
    assert info.concurrency is None and info.wallet is None
    assert not info.can_run_pairs


def test_bad_key_raises_clear_error():
    with pytest.raises(PermissionError):
        fetch_account(client_returning(401, {"message": "Access denied"}))


def test_live_shape_concurrency_object():
    """What Bolna actually returned on 2026-10-27."""
    info = fetch_account(client_returning(200, {"wallet": 500.0, "concurrency": {"max": 2, "current": 0}, "credit_limit": None}))
    assert info.concurrency == 2 and info.wallet == 500.0 and info.can_run_pairs
