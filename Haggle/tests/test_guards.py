"""Ticket #18: nothing may exceed the caps, whatever the code above does."""

from datetime import datetime, timezone

import pytest

from app import guards
from app.config import Settings
from app.models import Call, Order
from app.seed import ensure_demo_data


def settings(**kw):
    return Settings(_env_file=None, **kw)


def order(session):
    owner = ensure_demo_data(session)
    o = Order(owner_id=owner.id, items=[], deadline="07:00", state="COLLECTING_R1")
    session.add(o)
    session.commit()
    return o


def add_call(session, o, status="in-progress", rank=4, cost=None):
    c = Call(order_id=o.id, status=status, status_rank=rank, cost=cost, placed_at=datetime.now(timezone.utc))
    session.add(c)
    session.commit()
    return c


def test_ok_when_nothing_is_wrong(session):
    guards.check_can_dial(session, order(session).id, settings())


def test_kill_switch_stops_everything(session):
    with pytest.raises(guards.GuardRefused, match="kill switch"):
        guards.check_can_dial(session, order(session).id, settings(kill_switch=True))


def test_concurrency_limit_counts_calls_across_all_orders(session):
    o = order(session)
    add_call(session, o)
    add_call(session, o, status="ringing", rank=3)
    with pytest.raises(guards.GuardRefused, match="concurrency"):
        guards.check_can_dial(session, o.id, settings(concurrency_limit=2))
    guards.check_can_dial(session, o.id, settings(concurrency_limit=3))


def test_finished_and_pending_calls_do_not_use_a_slot(session):
    o = order(session)
    add_call(session, o, status="completed", rank=6, cost=3)
    add_call(session, o, status="pending", rank=-1)
    guards.check_can_dial(session, o.id, settings(concurrency_limit=1))


def test_order_cost_ceiling_uses_actuals_and_estimates(session):
    o = order(session)
    add_call(session, o, status="completed", rank=6, cost=50)  # actual
    add_call(session, o, status="completed", rank=6)           # unknown cost -> estimated at 6
    s = settings(cost_ceiling_per_order_inr=60, estimated_cost_per_call_inr=6, concurrency_limit=9, cost_unit_to_inr=1.0)
    # 50 + 6 already spent, +6 for the next call = 62 > 60
    with pytest.raises(guards.GuardRefused, match="per-order"):
        guards.check_can_dial(session, o.id, s)
    guards.check_can_dial(session, o.id, settings(cost_ceiling_per_order_inr=100, concurrency_limit=9))


def test_daily_cap(session):
    o = order(session)
    add_call(session, o, status="completed", rank=6, cost=290)
    s = settings(daily_cap_inr=300, cost_ceiling_per_order_inr=10_000, estimated_cost_per_call_inr=20, concurrency_limit=9,
                 cost_unit_to_inr=1.0)
    with pytest.raises(guards.GuardRefused, match="daily cap"):
        guards.check_can_dial(session, o.id, s)


def test_cap_of_zero_blocks_all_calls(session):
    with pytest.raises(guards.GuardRefused):
        guards.check_can_dial(session, order(session).id, settings(daily_cap_inr=0))


def test_cost_unit_conversion(session):
    o = order(session)
    add_call(session, o, status="completed", rank=6, cost=500)  # 500 "cents" = Rs 5
    s = settings(cost_unit_to_inr=0.01, cost_ceiling_per_order_inr=20, estimated_cost_per_call_inr=6, concurrency_limit=9)
    guards.check_can_dial(session, o.id, s)  # 5 + 6 = 11 <= 20


def test_one_live_order_per_owner(session):
    a = order(session)
    b = Order(owner_id=a.owner_id, items=[], deadline="07:00", state="DRAFT")
    session.add(b)
    session.commit()
    with pytest.raises(guards.GuardRefused, match="live order"):
        guards.check_can_start_order(session, a.owner_id, b.id, settings())
    a.state = "REPORTED"
    session.commit()
    guards.check_can_start_order(session, a.owner_id, b.id, settings())
