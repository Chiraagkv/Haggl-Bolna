"""Spending and dialing guards (ticket #18).

Checked before EVERY dial. A runaway retry loop can empty a wallet in minutes, so these are
code, not good intentions:

  * kill switch (KILL_SWITCH=true stops all dialing)
  * per-order cost ceiling and a daily spend cap (estimated cost of the next call is included)
  * concurrency: never more calls in flight than the account allows
  * one live order per owner
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import orders
from app.config import Settings
from app.models import Call, Order


class GuardRefused(RuntimeError):
    """A dial or an order start was refused. The message says which rule and why."""


IN_FLIGHT_RANKS = (1, 2, 3, 4, 5)  # queued .. call-disconnected: handed to Bolna, not yet finished


def in_flight_count(session: Session) -> int:
    """Calls Bolna is currently handling, across ALL orders (concurrency is per account)."""
    return session.scalar(select(func.count()).select_from(Call).where(Call.status_rank.in_(IN_FLIGHT_RANKS))) or 0


def order_spend_inr(session: Session, order_id: int, s: Settings) -> float:
    """Actual cost of finished calls plus an estimate for calls still in flight."""
    total = 0.0
    for c in session.scalars(select(Call).where(Call.order_id == order_id, Call.status_rank >= 1)):
        total += (c.cost * s.cost_unit_to_inr) if c.cost is not None else s.estimated_cost_per_call_inr
    return total


def daily_spend_inr(session: Session, s: Settings, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    total = 0.0
    for c in session.scalars(select(Call).where(Call.status_rank >= 1, Call.placed_at >= start)):
        total += (c.cost * s.cost_unit_to_inr) if c.cost is not None else s.estimated_cost_per_call_inr
    return total


def check_can_dial(session: Session, order_id: int | None, s: Settings, now: datetime | None = None) -> None:
    """Raise GuardRefused unless one more call may be placed right now."""
    if s.kill_switch:
        raise GuardRefused("kill switch is on")
    if in_flight_count(session) >= s.concurrency_limit:
        raise GuardRefused(f"concurrency limit {s.concurrency_limit} reached")
    nxt = s.estimated_cost_per_call_inr
    if order_id is not None and order_spend_inr(session, order_id, s) + nxt > s.cost_ceiling_per_order_inr:
        raise GuardRefused(f"per-order cost ceiling Rs {s.cost_ceiling_per_order_inr:g} would be exceeded")
    if daily_spend_inr(session, s, now) + nxt > s.daily_cap_inr:
        raise GuardRefused(f"daily cap Rs {s.daily_cap_inr:g} would be exceeded")


def check_can_start_order(session: Session, owner_id: int, order_id: int, s: Settings) -> None:
    if s.kill_switch:
        raise GuardRefused("kill switch is on")
    live = session.scalars(select(Order).where(Order.owner_id == owner_id, Order.id != order_id)).all()
    if any(orders.is_live(o.state) for o in live):
        raise GuardRefused("this owner already has a live order")
