from app import orchestrator as orc, orders, seed
from app.models import Call, Event, Order, Supplier
from sqlalchemy import select


def make(session, owner, **kw):
    spec = seed.demo_order_spec()
    o = orc.create_order(session, owner.id, spec["items"], kw.get("deadline", spec["deadline"]), kw.get("budget", spec["budget"]))
    return o


def run(session, order, fake):
    assert orc.start_order(session, order.id)
    orc.run_until_idle(session, fake)
    session.expire_all()
    return session.get(Order, order.id)


def test_happy_path(session, world, fake):
    o = run(session, make(session, world), fake)
    assert o.state == orders.REPORTED, o.failure_reason
    assert o.assignments == {"onions": "ramesh", "oil": "ramesh"}
    assert o.booked_total == 1100  # Ramesh after round 2: 25/kg and 60/L
    assert o.baseline_kind == "owner_last_paid_price" and o.savings == 200
    assert o.time_saved_min and o.time_saved_min > 0
    kinds = [c.kind for c in session.scalars(select(Call).order_by(Call.id))]
    assert kinds.count("supplier_r1") == 4 and kinds.count("supplier_r2") == 1  # only Ramesh has a real lower price to be shown
    assert "approval" not in kinds and kinds.count("confirm") == 1 and kinds.count("callback") == 1


def test_round2_only_cites_real_prices(session, world, fake):
    run(session, make(session, world), fake)
    r2 = [c for c in fake.placed if c.kind == "supplier_r2"]
    assert r2
    real = {25.0, 60.0, 26.0, 62.0, 27.0, 64.0}
    for c in r2:
        for offer in c.user_data["counter"]:
            assert offer["price"] in real


def test_concurrency_never_exceeded(session, world, fake, set_env):
    from app import guards
    peak = 0
    orig = fake.place_call

    def spy(kind, to, ud):
        nonlocal peak
        peak = max(peak, guards.in_flight_count(session) + 1)
        return orig(kind, to, ud)
    fake.place_call = spy
    run(session, make(session, world), fake)
    assert peak <= 2


def test_over_budget_needs_approval_yes(session, world, fake):
    o = run(session, make(session, world, budget=1000), fake)
    assert o.state == orders.REPORTED and o.approval["status"] == "approved"
    assert any(c.kind == "approval" for c in fake.placed)


def test_over_budget_owner_says_no(session, world, fake):
    fake.owner = "no"
    o = run(session, make(session, world, budget=1000), fake)
    assert o.state == orders.FAILED and o.failure_reason == "owner_declined"
    assert not any(c.kind == "confirm" for c in fake.placed)  # never booked


def test_approval_unanswered_never_books(session, world, fake):
    fake.owner = "no-answer"
    o = run(session, make(session, world, budget=1000), fake)
    assert o.state == orders.FAILED and not any(c.kind == "confirm" for c in fake.placed)


def test_split_basket(session, world, fake):
    fake.use_split_variant = True
    o = run(session, make(session, world), fake)
    assert o.state == orders.REPORTED
    assert o.assignments == {"onions": "lakshmi", "oil": "ramesh"} or o.assignments["oil"] == "ramesh"
    assert len({c.user_data["supplier_key"] for c in fake.placed if c.kind == "confirm"}) == len(set(o.assignments.values()))


def test_no_answer_and_voicemail(session, world, fake):
    fake.behaviour.update(kumar="no-answer", gowda="voicemail")
    o = run(session, make(session, world), fake)
    assert o.state == orders.REPORTED
    session.expire_all()
    assert session.scalar(select(Supplier).where(Supplier.key == "kumar")).no_answer_count == 2  # first try + one retry


def test_everyone_silent_fails_cleanly(session, world, fake):
    for k in ("kumar", "ramesh", "gowda", "lakshmi"):
        fake.behaviour[k] = "no-answer"
    o = run(session, make(session, world), fake)
    assert o.state == orders.FAILED and o.failure_reason == "no_quotes"


def test_late_supplier_filtered(session, world, fake):
    fake.behaviour["ramesh"] = "late"
    o = run(session, make(session, world), fake)
    assert o.state == orders.REPORTED and "ramesh" not in o.assignments.values()


def test_confirm_refused_goes_to_runner_up(session, world, fake):
    fake.behaviour["ramesh"] = "refuses_confirm"
    o = run(session, make(session, world), fake)
    assert o.state == orders.REPORTED and "ramesh" not in o.assignments.values()
    assert o.booking_attempts == 1 and o.excluded_suppliers == ["ramesh"]


def test_wrong_quantity_confirmation_rejected(session, world, fake):
    fake.behaviour["ramesh"] = "wrong_quantity"
    o = run(session, make(session, world), fake)
    assert "ramesh" not in (o.assignments or {}).values() or o.state == orders.FAILED


def test_booking_gives_up_after_max_attempts(session, world, fake):
    for k in ("kumar", "ramesh", "gowda", "lakshmi"):
        fake.behaviour[k] = "refuses_confirm"
    o = run(session, make(session, world), fake)
    assert o.state == orders.FAILED and o.failure_reason == "booking_failed"


def test_lost_webhook_recovered_by_polling(session, world, fake, set_env):
    from datetime import timedelta
    fake.behaviour["kumar"] = "lost_webhook"
    order = make(session, world)
    orc.start_order(session, order.id)
    future = lambda: orc.now_utc() + timedelta(seconds=120)  # noqa: E731
    orc.run_until_idle(session, fake, now_fn=future)
    session.expire_all()
    assert session.get(Order, order.id).state == orders.REPORTED


def test_hung_call_does_not_block_past_deadline(session, world, fake):
    from datetime import timedelta
    fake.behaviour["gowda"] = "hang"
    order = make(session, world)
    orc.start_order(session, order.id)
    orc.run_until_idle(session, fake)
    session.expire_all()
    assert session.get(Order, order.id).state == orders.COLLECTING_R1  # still waiting for gowda
    far = lambda: orc.now_utc() + timedelta(seconds=10_000)  # noqa: E731
    orc.run_until_idle(session, fake, now_fn=far)
    session.expire_all()
    assert session.get(Order, order.id).state in (orders.REPORTED, orders.FAILED)


def test_do_not_call_honoured(session, world, fake):
    fake.behaviour["kumar"] = "do_not_call"
    run(session, make(session, world), fake)
    assert session.scalar(select(Supplier).where(Supplier.key == "kumar")).do_not_call is True
    o2 = make(session, world)
    session.expire_all()
    n_before = len([c for c in fake.placed if c.user_data.get("supplier_key") == "kumar"])
    run(session, o2, fake)
    assert len([c for c in fake.placed if c.user_data.get("supplier_key") == "kumar"]) == n_before


def test_bad_unit_is_flagged_not_guessed(session, world, fake):
    fake.behaviour["ramesh"] = "bad_unit"
    o = run(session, make(session, world), fake)
    assert o.state == orders.REPORTED and "ramesh" not in o.assignments.values()
    assert o.ranking["flagged"]


def test_cost_ceiling_stops_dialing(session, world, fake, set_env):
    set_env(COST_CEILING_PER_ORDER_INR=12)
    o = run(session, make(session, world), fake)
    assert len(fake.placed) <= 2
    assert o.state in (orders.FAILED, orders.REPORTED)


def test_kill_switch(session, world, fake, set_env):
    set_env(KILL_SWITCH="true")
    order = make(session, world)
    assert not orc.start_order(session, order.id)
    assert not fake.placed


def test_second_order_blocked_while_live(session, world, fake):
    a = make(session, world)
    assert orc.start_order(session, a.id)
    b = make(session, world)
    assert not orc.start_order(session, b.id)
    session.expire_all()
    assert session.get(Order, b.id).state == orders.FAILED


def test_invalid_orders_rejected(session, world):
    import pytest
    for items, dl in ([[], "07:00"], [[{"name": "onions", "quantity": -1, "unit": "kg"}], "07:00"],
                      [[{"name": "onions", "quantity": 20, "unit": "petti"}], "07:00"],
                      [[{"name": "onions", "quantity": 99999, "unit": "kg"}], "07:00"],
                      [[{"name": "onions", "quantity": 5, "unit": "kg"}], "soon"]):
        with pytest.raises(orc.OrderInvalid):
            orc.create_order(session, world.id, items, dl)


def test_events_feed_complete(session, world, fake):
    o = run(session, make(session, world), fake)
    evs = orders.events_after(session, o.id, 0, 1000)
    types = [e.kind for e in evs]
    for t in ("created", "state", "call_planned", "call_placed", "quote", "notify"):
        assert t in types
    ids = [e.id for e in evs]
    assert ids == sorted(ids)


def test_intake_creates_and_runs_order(session, world, fake):
    import json
    payload = {"id": "inbound-1", "status": "completed", "conversation_duration": 30, "total_cost": 3,
               "transcript": "owner: 20 kilo pyaaz", "context_details": {},
               "extracted_data": {"Order": {"order_json": {"subjective": json.dumps(
                   {"items": [{"name": "onions", "quantity": 20, "unit": "kg"}, {"name": "oil", "quantity": 10, "unit": "litre"}],
                    "deadline": "7 am", "budget": 1200})}}}}
    orc.process_webhook(session, payload)
    orc.run_until_idle(session, fake)
    session.expire_all()
    o = session.scalar(select(Order))
    assert o is not None and o.state == orders.REPORTED


def test_no_answer_gets_exactly_one_retry(session, world, fake):
    fake.behaviour["kumar"] = "no-answer"
    run(session, make(session, world), fake)
    assert len([c for c in fake.placed if c.user_data.get("supplier_key") == "kumar" and c.kind == "supplier_r1"]) == 2


def test_retry_can_be_switched_off(session, world, fake, set_env):
    set_env(RETRY_NO_ANSWER="false")
    fake.behaviour["kumar"] = "no-answer"
    run(session, make(session, world), fake)
    assert len([c for c in fake.placed if c.user_data.get("supplier_key") == "kumar"]) == 1


def test_outbound_intake_call_makes_and_runs_an_order(session, world, fake, set_env):
    set_env(OWNER_PHONE_OVERRIDE="+919800000001")
    orc.plan_intake_call(session, world.id)
    orc.run_until_idle(session, fake)
    session.expire_all()
    o = session.scalar(select(Order))
    assert o is not None and o.state == orders.REPORTED and o.deadline == "07:00"


def test_bad_intake_is_rejected_not_booked(session, world, fake, set_env):
    set_env(OWNER_PHONE_OVERRIDE="+919800000001")
    fake.intake_order = {"items": [{"name": "onions", "quantity": 20000, "unit": "kg"}], "deadline": "07:00"}
    orc.plan_intake_call(session, world.id)
    orc.run_until_idle(session, fake)
    assert session.scalar(select(Order)) is None
    assert session.scalar(select(Event).where(Event.kind == "intake_rejected")) is not None


def test_live_mode_skips_suppliers_it_may_not_dial(session, world, fake, set_env):
    set_env(PROVIDER="bolna", VERIFIED_NUMBERS="+911", REQUIRE_VERIFIED_NUMBERS="true")
    order = make(session, world)
    assert orc.select_suppliers(session, order) == []


def test_fake_ids_do_not_repeat_after_a_restart(session, world, fake):
    from app import providers
    run(session, make(session, world), fake)
    providers.set_provider(providers.FakeProvider(delay=0))  # what a server restart does, with the same database
    o = run(session, make(session, world), providers.get_provider())
    assert o.state == orders.REPORTED, o.failure_reason
