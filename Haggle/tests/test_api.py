def run_ticks(client, n=40):
    for _ in range(n):
        client.post("/api/tick")


def test_demo_flow_through_api(client, fake):
    r = client.post("/api/demo/start")
    assert r.status_code == 200 and r.json()["started"]
    oid = r.json()["order_id"]
    run_ticks(client)
    s = client.get(f"/api/orders/{oid}/state").json()
    assert s["order"]["state"] == "REPORTED"
    assert s["order"]["booked_total"] == 1100 and s["order"]["savings"] == 200
    assert s["ranking"]["ranked"][0]["key"] == "ramesh"
    assert any(q["round"] == 2 for q in s["quotes"])
    assert s["feed"] and s["last_event_id"] > 0
    m = client.get("/api/metrics").json()
    assert m["booked"] == 1 and m["total_savings_inr"] == 200 and m["completion_rate"] == 1.0


def test_dashboard_and_health(client):
    html = client.get("/").text
    assert "Dalaal" in html and "/api/orders" in html
    assert client.get("/health").json()["provider"] == "fake"


def test_create_order_validation(client, fake):
    client.post("/api/demo/start")
    bad = client.post("/api/orders", json={"items": [{"name": "onions", "quantity": -3, "unit": "kg"}], "deadline": "07:00"})
    assert bad.status_code == 422


def test_demo_refuses_real_provider(client, set_env):
    set_env(PROVIDER="bolna")
    assert client.post("/api/demo/start").status_code == 409


def test_kill_endpoint(client, fake):
    oid = client.post("/api/demo/start").json()["order_id"]
    assert client.post(f"/api/orders/{oid}/kill").json()["failed"]
    assert client.get(f"/api/orders/{oid}/state").json()["order"]["failure_reason"] == "stopped_by_operator"


def test_deliveries_update_reliability(client, fake):
    client.post("/api/demo/start")
    r = client.post("/api/deliveries", json={"supplier_key": "kumar", "on_time": False})
    assert r.json() == {"on_time": 1, "late": 3}


def test_stream_replays_after_last_id(session, fake):
    from app import orders, orchestrator as orc, seed
    owner = seed.ensure_demo_data(session)
    o = orc.create_order(session, owner.id, seed.demo_order_spec()["items"], "07:00", 1200)
    orc.start_order(session, o.id)
    first = orders.events_after(session, o.id, 0)
    later = orders.events_after(session, o.id, first[0].id)
    assert [e.id for e in later] == [e.id for e in first[1:]]


def test_preflight_fake_is_ready(client):
    r = client.get("/api/preflight").json()
    assert r["ready"] and not r["live"]


def test_preflight_live_lists_what_is_missing(client, set_env):
    set_env(PROVIDER="bolna")
    r = client.get("/api/preflight").json()
    bad = {c["name"] for c in r["checks"] if not c["ok"]}
    assert not r["ready"] and {"Bolna API key", "public URL", "supplier agent (round 1)", "seeded data"} <= bad
    assert r["manual_steps"] == []  # tool + extractions are created through the API now


def test_envfile_updates_in_place(tmp_path):
    from app import envfile
    p = tmp_path / ".env"
    p.write_text("A=1\n# B=old\nB=2\n")
    envfile.set_values(p, {"B": "3", "C": "4"})
    assert p.read_text() == "A=1\n# B=old\nB=3\nC=4\n"


ORDER = {"items": [{"name": "onions", "quantity": 20, "unit": "kg"}, {"name": "oil", "quantity": 10, "unit": "litre"}],
         "deadline": "07:00", "budget": 1200}


def test_preview_shows_pairs_and_saves_nothing(client, session):
    from app.models import Call, Order
    setup = client.get("/api/setup").json()
    assert setup["provider"] == "fake" and "onions" in setup["known_items"]
    p = client.post("/api/orders/preview", json={**ORDER, "items": ORDER["items"] + [{"name": "rice", "quantity": 5, "unit": "kg"}]}).json()
    assert [[x["key"] for x in w] for w in p["waves"]] == [["kumar", "ramesh"], ["gowda", "lakshmi"]]
    assert p["uncovered"] == ["rice"] and p["estimated_cost_inr"] > 0
    assert session.query(Order).count() == 0 and session.query(Call).count() == 0


def test_receipt_appears_only_when_booked(client, session, fake):
    from app import orchestrator
    client.get("/api/setup")  # seeds the demo owner in fake mode
    oid = client.post("/api/orders", json=ORDER).json()["order_id"]
    assert client.get(f"/api/orders/{oid}/state").json()["receipt"] is None
    orchestrator.run_until_idle(session, fake)
    rc = client.get(f"/api/orders/{oid}/state").json()["receipt"]
    assert rc["total"] == 1100 and rc["savings"] == 200
    [ramesh] = rc["suppliers"]
    assert {(x["item"], x["unit_price"], x["amount"]) for x in ramesh["lines"]} == {("onions", 25.0, 500.0), ("oil", 60.0, 600.0)}
