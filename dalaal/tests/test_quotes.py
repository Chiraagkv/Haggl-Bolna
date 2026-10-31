"""Tickets #10 and #11: quotes from the extraction at `completed` and from the live
`submit_quote` tool, with the provisional -> confirmed rule (Bible edge cases 15 and 16)."""

import json

from sqlalchemy import func, select

from app import services
from app.models import Call, Event, Quote


def extraction(quotes):
    """Shape of Bolna's extracted_data: {category: {extraction_name: {subjective, ...}}}."""
    return {"Dalaal": {"quotes_json": {"subjective": json.dumps(quotes), "objective": None, "confidence": 0.9}}}


def completed(exec_id, quotes):
    return {"id": exec_id, "status": "completed", "extracted_data": extraction(quotes)}


def tool(client, body, headers=None):
    return client.post("/tools/submit_quote", json=body, headers=headers or {})


def quotes(session):
    session.expire_all()
    return list(session.scalars(select(Quote).order_by(Quote.id)))


def test_extraction_at_completed_creates_confirmed_quote(client, session):
    client.post("/webhook/bolna", json=completed("e1", [
        {"item": "Onions", "unit_price": "25", "unit": "kg", "available": True, "delivery_time": "07:00",
         "credit_days": 0, "delivery_fee": 0, "what_they_said": "pyaaz pachchis rupaye kilo"}]))
    (q,) = quotes(session)
    assert q.item == "onions" and q.unit_price == 25 and q.price_per_base == 25
    assert q.provisional is False and q.source == "extraction" and not q.flagged
    assert q.raw_text == "pyaaz pachchis rupaye kilo"


def test_replaying_completed_does_not_duplicate_quotes(client, session):
    body = completed("e1", [{"item": "onions", "unit_price": 25, "unit": "kg"}])
    for _ in range(3):
        client.post("/webhook/bolna", json=body)
    assert len(quotes(session)) == 1


def test_submit_quote_creates_provisional_quote(client, session):
    r = tool(client, {"call_ref": "r1", "item": "onions", "unit_price": 25, "unit": "kg", "available": True})
    assert r.status_code == 200 and r.json()["provisional"] is True
    (q,) = quotes(session)
    assert q.provisional is True and q.source == "submit_quote"


def test_submit_quote_twice_is_one_row(client, session):
    for _ in range(2):
        tool(client, {"call_ref": "r1", "item": "onions", "unit_price": 25, "unit": "kg"})
    assert len(quotes(session)) == 1


def test_supplier_correcting_himself_updates_the_provisional_quote(client, session):
    tool(client, {"call_ref": "r1", "item": "onions", "unit_price": 25, "unit": "kg"})
    tool(client, {"call_ref": "r1", "item": "onions", "unit_price": 24, "unit": "kg"})
    (q,) = quotes(session)
    assert q.unit_price == 24 and q.provisional is True


def test_edge_case_15_extraction_overrides_a_contradicted_live_quote(client, session):
    # live tool heard 52, the supplier actually said 25; the confirmed extraction wins
    tool(client, {"call_ref": "r1", "execution_id": "e1", "item": "onions", "unit_price": 52, "unit": "kg"})
    client.post("/webhook/bolna", json=completed("e1", [{"item": "onions", "unit_price": 25, "unit": "kg"}]))
    (q,) = quotes(session)
    assert q.unit_price == 25 and q.provisional is False and q.source == "extraction"
    assert session.scalar(select(func.count()).select_from(Call)) == 1  # tool and webhook joined one call


def test_late_tool_call_never_overwrites_a_confirmed_quote(client, session):
    client.post("/webhook/bolna", json=completed("e1", [{"item": "onions", "unit_price": 25, "unit": "kg"}]))
    tool(client, {"execution_id": "e1", "item": "onions", "unit_price": 99, "unit": "kg"})
    (q,) = quotes(session)
    assert q.unit_price == 25 and q.provisional is False


def test_edge_case_16_tool_never_fires_extraction_still_gives_the_quote(client, session):
    client.post("/webhook/bolna", json=completed("e1", [{"item": "oil", "unit_price": 62, "unit": "litre"}]))
    (q,) = quotes(session)
    assert q.item == "oil" and q.price_per_base == 62


def test_spoken_price_text_is_parsed(client, session):
    tool(client, {"call_ref": "r1", "item": "onions", "unit_price": "पच्चीस रुपये किलो"})
    (q,) = quotes(session)
    assert q.unit_price == 25 and q.unit == "kg" and not q.flagged


def test_quintal_is_normalised_to_per_kg(client, session):
    tool(client, {"call_ref": "r1", "item": "onions", "unit_price": 2500, "unit": "quintal"})
    (q,) = quotes(session)
    assert q.unit == "quintal" and q.unit_price == 2500 and q.price_per_base == 25 and q.base_unit == "kg"


def test_unknown_unit_is_flagged_not_guessed(client, session):
    tool(client, {"call_ref": "r1", "item": "onions", "unit_price": 800, "unit": "petti"})
    (q,) = quotes(session)
    assert q.flagged and q.price_per_base is None and "no fixed size" in q.flag_reason


def test_missing_unit_is_flagged(client, session):
    tool(client, {"call_ref": "r1", "item": "onions", "unit_price": 25})
    (q,) = quotes(session)
    assert q.flagged


def test_credit_and_delivery_fee_are_stored(client, session):
    tool(client, {"call_ref": "r1", "item": "onions", "unit_price": 25, "unit": "kg",
                  "credit_days": "7", "delivery_fee": 40, "delivery_time": "06:30"})
    (q,) = quotes(session)
    assert q.credit_days == 7 and q.delivery_fee == 40 and q.delivery_time == "06:30"


def test_tool_requires_item_and_a_call_identifier(client):
    assert tool(client, {"call_ref": "r1", "unit_price": 25}).status_code == 422
    assert tool(client, {"item": "onions", "unit_price": 25}).status_code == 422


def test_tool_secret_is_enforced_when_set(client, set_env):
    set_env(TOOL_SECRET="s3cret")
    body = {"call_ref": "r1", "item": "onions", "unit_price": 25, "unit": "kg"}
    assert tool(client, body).status_code == 401
    assert tool(client, body, headers={"X-Dalaal-Token": "wrong"}).status_code == 401
    assert tool(client, body, headers={"X-Dalaal-Token": "s3cret"}).status_code == 200


def test_get_variant_works_for_query_parameters(client, session):
    r = client.get("/tools/submit_quote", params={"call_ref": "r1", "item": "onions", "unit_price": "25", "unit": "kg"})
    assert r.status_code == 200
    assert len(quotes(session)) == 1


def test_tool_calls_are_logged_raw(client, session):
    tool(client, {"call_ref": "r1", "item": "onions", "unit_price": 25, "unit": "kg"})
    assert session.scalar(select(Event).where(Event.kind == "tool")) is not None


def test_garbage_extraction_creates_no_quotes_and_no_crash(client, session):
    for bad in [None, {}, {"Dalaal": {"quotes_json": {"subjective": "not json"}}},
                {"Dalaal": {"quotes_json": {"subjective": ""}}}, {"x": 1}]:
        r = client.post("/webhook/bolna", json={"id": "eg", "status": "completed", "extracted_data": bad})
        assert r.status_code == 200
    assert quotes(session) == []


def test_code_fenced_json_is_accepted():
    fenced = "```json\n[{\"item\": \"oil\", \"unit_price\": 60, \"unit\": \"litre\"}]\n```"
    out = services.quotes_from_extracted_data({"Dalaal": {"quotes_json": {"subjective": fenced}}})
    assert out == [{"item": "oil", "unit_price": 60, "unit": "litre"}]


def test_debug_calls_shows_quotes(client):
    tool(client, {"call_ref": "r1", "item": "onions", "unit_price": 25, "unit": "kg"})
    rows = client.get("/debug/calls").json()
    assert rows[0]["quotes"][0]["item"] == "onions" and rows[0]["quotes"][0]["provisional"] is True
