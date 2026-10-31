from datetime import datetime, timezone

import httpx
import pytest

from app.bolna_client import BolnaClient, BolnaError, format_scheduled_at


def client_with(handler):
    return BolnaClient(api_key="k", base_url="https://api.bolna.ai", transport=httpx.MockTransport(handler))


def test_create_agent_expects_201_and_reads_state():
    def handler(req):
        assert req.method == "POST" and req.url.path == "/v2/agent"
        assert req.headers["Authorization"] == "Bearer k"
        return httpx.Response(201, json={"agent_id": "a1", "state": "created"})

    assert client_with(handler).create_agent({"agent_config": {}})["agent_id"] == "a1"


def test_create_agent_200_is_treated_as_wrong_endpoint():
    # 200 is what the old /agent endpoint returns; /v2/agent must return 201
    with pytest.raises(BolnaError):
        client_with(lambda r: httpx.Response(200, json={"agent_id": "a1"})).create_agent({})


def test_make_call_returns_execution_id():
    def handler(req):
        assert req.url.path == "/call"
        import json

        body = json.loads(req.content)
        assert body["agent_id"] == "a1" and body["recipient_phone_number"] == "+911234567890"
        assert body["user_data"] == {"call_ref": "r1"} and "from_phone_number" not in body
        return httpx.Response(200, json={"message": "done", "status": "queued", "execution_id": "ex1"})

    out = client_with(handler).make_call("a1", "+911234567890", user_data={"call_ref": "r1"})
    assert out["execution_id"] == "ex1" and out["status"] == "queued"


def test_make_call_error_is_raised_with_body():
    with pytest.raises(BolnaError) as e:
        client_with(lambda r: httpx.Response(400, json={"error": 400, "message": "bad number"})).make_call("a", "x")
    assert e.value.status_code == 400 and "bad number" in str(e.value)


def test_bad_key_gives_a_clear_error():
    with pytest.raises(BolnaError, match="401"):
        client_with(lambda r: httpx.Response(401, json={"message": "Access denied"})).get_execution("x")


def test_get_execution():
    c = client_with(lambda r: httpx.Response(200, json={"id": "ex1", "status": "completed"}))
    assert c.get_execution("ex1")["status"] == "completed"


def test_missing_key_is_refused():
    with pytest.raises(BolnaError):
        BolnaClient(api_key="")


def test_scheduled_at_uses_numeric_offset_never_z():
    now = datetime(2026, 10, 26, 12, 0, 0, 123456, tzinfo=timezone.utc)
    s = format_scheduled_at(3, now=now)
    assert s == "2026-10-26T12:03:00+00:00"
    assert not s.endswith("Z")


def test_scheduled_at_must_be_two_minutes_ahead():
    with pytest.raises(ValueError):
        format_scheduled_at(1)
