"""Tickets #8 and #9: the webhook stores the raw event first, answers 200, and every replay,
duplicate or out-of-order delivery changes nothing it should not."""

from sqlalchemy import func, select

from app import services
from app.models import Call, Event


def payload(status, exec_id="exec-1", **extra):
    return {"id": exec_id, "agent_id": "agent-1", "status": status, **extra}


def post(client, body, headers=None):
    return client.post("/webhook/bolna", json=body, headers=headers or {})


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_raw_event_is_stored_and_call_created(client, session):
    r = post(client, payload("queued"))
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert count(session, Event) == 1
    call = session.scalar(select(Call))
    assert call.execution_id == "exec-1" and call.status == "queued"


def test_same_payload_five_times_makes_one_call_and_five_events(client, session):
    for _ in range(5):
        assert post(client, payload("ringing")).status_code == 200
    assert count(session, Call) == 1
    assert count(session, Event) == 5


def test_late_ringing_after_completed_does_not_regress(client, session):
    post(client, payload("completed"))
    post(client, payload("ringing"))
    session.expire_all()
    assert session.scalar(select(Call)).status == "completed"


def test_status_moves_forward_through_the_whole_lifecycle(client, session):
    for st in ["queued", "initiated", "ringing", "in-progress", "call-disconnected", "completed"]:
        post(client, payload(st))
        session.expire_all()
        assert session.scalar(select(Call)).status == st


def test_advanced_flag_is_true_once_then_false(session):
    p = payload("ringing")
    first = services.apply_webhook(session, p)
    second = services.apply_webhook(session, p)
    assert first["advanced"] is True and second["advanced"] is False


def test_terminal_status_is_final(client, session):
    post(client, payload("no-answer"))
    post(client, payload("in-progress"))
    session.expire_all()
    assert session.scalar(select(Call)).status == "no-answer"


def test_every_terminal_status_is_accepted(client, session):
    for i, st in enumerate(["completed", "no-answer", "busy", "failed", "canceled", "stopped", "error", "balance-low"]):
        post(client, payload(st, exec_id=f"e{i}"))
    session.expire_all()
    assert {c.status for c in session.scalars(select(Call))} == {
        "completed", "no-answer", "busy", "failed", "canceled", "stopped", "error", "balance-low"
    }


def test_data_is_not_trusted_before_completed(client, session):
    # call-disconnected has zero cost/duration in Bolna: we must not store those. Its transcript is
    # already final live, so it is shown early, and the `completed` one still replaces it.
    post(client, payload("call-disconnected", transcript="partial", total_cost=0, conversation_duration=0))
    session.expire_all()
    c = session.scalar(select(Call))
    assert c.transcript == "partial" and c.cost is None
    post(client, payload("completed", transcript="full", total_cost=6, conversation_duration=60))
    session.expire_all()
    assert session.scalar(select(Call)).transcript == "full"


def test_completed_fills_data_once_and_replay_does_not_overwrite(client, session):
    full = payload(
        "completed",
        transcript="assistant: hello",
        total_cost=3.23,
        conversation_duration=16,
        telephony_data={"recording_url": "https://api.bolna.ai/recordings/call/x"},
        answered_by_voice_mail=False,
    )
    post(client, full)
    post(client, {**full, "transcript": "SOMETHING ELSE", "total_cost": 99})
    session.expire_all()
    c = session.scalar(select(Call))
    assert c.transcript == "assistant: hello" and c.cost == 3.23 and c.duration == 16
    assert c.recording_url.endswith("/x") and c.completed_at is not None


def test_unknown_status_is_stored_but_changes_nothing(client, session):
    post(client, payload("queued"))
    assert post(client, payload("some-future-status")).status_code == 200
    session.expire_all()
    assert session.scalar(select(Call)).status == "queued"
    assert count(session, Event) == 2


def test_call_matched_by_call_ref_when_execution_id_is_new(client, session):
    services.get_or_create_call(session, call_ref="ref-9")
    post(client, payload("ringing", exec_id="exec-new", context_details={"call_ref": "ref-9"}))
    session.expire_all()
    calls = session.scalars(select(Call)).all()
    assert len(calls) == 1 and calls[0].execution_id == "exec-new" and calls[0].call_ref == "ref-9"


def test_malformed_json_is_answered_200_and_kept(client, session):
    r = client.post("/webhook/bolna", content=b"not json {", headers={"content-type": "application/json"})
    assert r.status_code == 200
    ev = session.scalar(select(Event))
    assert ev.payload is None and ev.raw_text == "not json {"


def test_processing_failure_is_swallowed_but_raw_event_survives(client, session, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("bug")

    monkeypatch.setattr(services, "apply_webhook", boom)
    assert post(client, payload("completed")).status_code == 200
    assert count(session, Event) == 1


def test_payload_without_any_id_is_ignored_safely(client, session):
    assert post(client, {"status": "completed"}).status_code == 200
    assert count(session, Call) == 0 and count(session, Event) == 1


def test_source_ip_enforcement(client, set_env):
    set_env(ENFORCE_WEBHOOK_IPS="true")
    ok = post(client, payload("queued"), headers={"X-Forwarded-For": "13.203.39.153"})
    bad = post(client, payload("queued"), headers={"X-Forwarded-For": "1.2.3.4"})
    assert ok.status_code == 200 and bad.status_code == 403


def test_ips_not_enforced_by_default(client):
    assert post(client, payload("queued"), headers={"X-Forwarded-For": "1.2.3.4"}).status_code == 200
