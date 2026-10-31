"""Tickets #15, #16, #17: schema, conditional transitions, and the event feed."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import orders
from app.models import Call, Event, Order, Owner, Supplier
from app.seed import ensure_demo_data


def make_order(session, state="DRAFT"):
    owner = ensure_demo_data(session)
    o = Order(owner_id=owner.id, items=[{"name": "onions", "quantity": 20, "unit": "kg"}], deadline="07:00",
              budget=1200, state=state)
    session.add(o)
    session.commit()
    return o


def test_seed_is_idempotent_and_matches_personas(session):
    ensure_demo_data(session)
    ensure_demo_data(session)
    assert session.scalar(select(func.count()).select_from(Owner)) == 1
    keys = {s.key: s for s in session.scalars(select(Supplier))}
    assert set(keys) == {"kumar", "ramesh", "gowda", "lakshmi"}
    assert (keys["kumar"].on_time_count, keys["kumar"].late_count) == (1, 2)
    assert keys["lakshmi"].items == ["onions"]  # no oil


def test_supplier_unique_per_owner(session):
    owner = ensure_demo_data(session)
    session.add(Supplier(owner_id=owner.id, key="kumar", name="dup"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_execution_id_unique_constraint_from_phase1_still_holds(session):
    session.add_all([Call(execution_id="x"), Call(execution_id="x")])
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_full_legal_path(session):
    o = make_order(session)
    path = [orders.COLLECTING_R1, orders.RANKED, orders.NEGOTIATING_R2, orders.RERANKED,
            orders.AWAITING_APPROVAL, orders.BOOKING, orders.BOOKED, orders.REPORTED]
    for st in path:
        assert orders.transition(session, o.id, st) is True
        assert orders.get_order(session, o.id).state == st
    assert orders.get_order(session, o.id).finished_at is not None


def test_illegal_jump_is_refused(session):
    o = make_order(session)
    assert orders.transition(session, o.id, orders.BOOKED) is False
    assert orders.get_order(session, o.id).state == orders.DRAFT


def test_backwards_move_is_refused(session):
    o = make_order(session, state=orders.BOOKING)
    assert orders.transition(session, o.id, orders.COLLECTING_R1) is False


def test_terminal_states_are_final(session):
    o = make_order(session, state=orders.REPORTED)
    assert orders.fail(session, o.id, "late") is False
    f = make_order(session)
    assert orders.fail(session, f.id, "boom") is True
    assert orders.transition(session, f.id, orders.COLLECTING_R1) is False
    assert orders.get_order(session, f.id).failure_reason == "boom"


def test_double_fire_has_exactly_one_winner(session):
    o = make_order(session, state=orders.COLLECTING_R1)
    results = [orders.transition(session, o.id, orders.RANKED, expect={orders.COLLECTING_R1}) for _ in range(2)]
    assert results == [True, False]
    assert session.scalar(select(func.count()).select_from(Event).where(Event.kind == "state")) == 1


def test_expect_narrows_allowed_from_states(session):
    o = make_order(session, state=orders.RERANKED)
    assert orders.transition(session, o.id, orders.BOOKING, expect={orders.AWAITING_APPROVAL}) is False
    assert orders.transition(session, o.id, orders.BOOKING, expect={orders.RERANKED}) is True


def test_every_state_has_a_legal_exit_except_terminals():
    for st, targets in orders.LEGAL.items():
        assert (not targets) == (st in orders.TERMINAL_STATES)
        assert orders.FAILED in targets or st in orders.TERMINAL_STATES


def test_event_feed_resumes_after_last_seen_id(session):
    o = make_order(session)
    other = make_order(session)
    orders.emit(session, o.id, "a")
    orders.emit(session, o.id, "b")
    orders.emit(session, other.id, "noise")
    evs = orders.events_after(session, o.id)
    assert [e.kind for e in evs] == ["a", "b"]
    assert [e.kind for e in orders.events_after(session, o.id, last_id=evs[0].id)] == ["b"]
    assert orders.events_after(session, o.id, last_id=evs[-1].id) == []
