"""Order state machine and the event feed (tickets #16 and #17).

Every transition is a conditional UPDATE (`... WHERE state IN (allowed)`), so two things
happening at once cannot both win: whichever commits second changes zero rows and does nothing.
Every change also writes an `events` row, which is what the dashboard and any recovery read.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Event, Order

DRAFT = "DRAFT"
COLLECTING_R1 = "COLLECTING_R1"
RANKED = "RANKED"
NEGOTIATING_R2 = "NEGOTIATING_R2"
RERANKED = "RERANKED"
AWAITING_APPROVAL = "AWAITING_APPROVAL"
BOOKING = "BOOKING"
BOOKED = "BOOKED"
REPORTED = "REPORTED"
FAILED = "FAILED"

TERMINAL_STATES = frozenset({REPORTED, FAILED})

# from-state -> states it may move to
LEGAL: dict[str, frozenset[str]] = {
    DRAFT: frozenset({COLLECTING_R1, FAILED}),
    COLLECTING_R1: frozenset({RANKED, FAILED}),
    RANKED: frozenset({NEGOTIATING_R2, RERANKED, AWAITING_APPROVAL, BOOKING, FAILED}),
    NEGOTIATING_R2: frozenset({RERANKED, FAILED}),
    RERANKED: frozenset({AWAITING_APPROVAL, BOOKING, FAILED}),
    AWAITING_APPROVAL: frozenset({BOOKING, FAILED}),
    BOOKING: frozenset({BOOKED, FAILED}),
    BOOKED: frozenset({REPORTED, FAILED}),
    REPORTED: frozenset(),
    FAILED: frozenset(),
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_live(state: str) -> bool:
    return state not in TERMINAL_STATES and state != DRAFT


def emit(session: Session, order_id: int | None, type_: str, payload: dict | None = None) -> Event:
    """Append to the event log (the dashboard's feed and the recovery record)."""
    ev = Event(kind=type_, order_id=order_id, payload=payload or {})
    session.add(ev)
    session.commit()
    return ev


def transition(session: Session, order_id: int, to_state: str, *, expect: set[str] | frozenset[str] | None = None,
               **fields: Any) -> bool:
    """Move an order to `to_state`. Returns True if THIS call made the move.

    `expect` narrows the allowed from-states (default: every state from which the move is legal).
    Illegal moves and lost races both return False and change nothing.
    """
    legal_from = {s for s, targets in LEGAL.items() if to_state in targets}
    allowed = legal_from if expect is None else (legal_from & set(expect))
    if not allowed:
        return False
    values: dict[str, Any] = {"state": to_state, "updated_at": utcnow(), "stage_started_at": utcnow(), **fields}
    if to_state in TERMINAL_STATES:
        values["finished_at"] = utcnow()
    res = session.execute(update(Order).where(Order.id == order_id, Order.state.in_(allowed)).values(**values))
    session.commit()
    if res.rowcount != 1:
        return False
    emit(session, order_id, "state", {"state": to_state, **({"reason": fields["failure_reason"]} if "failure_reason" in fields else {})})
    return True


def fail(session: Session, order_id: int, reason: str) -> bool:
    return transition(session, order_id, FAILED, failure_reason=reason)


def get_order(session: Session, order_id: int) -> Order | None:
    session.expire_all()
    return session.get(Order, order_id)


def events_after(session: Session, order_id: int | None, last_id: int = 0, limit: int = 200) -> list[Event]:
    """Events newer than `last_id` for one order (or all orders if order_id is None), oldest first.

    The dashboard stays correct after a dropped connection by asking for everything after the
    last id it saw; nothing lives only in memory.
    """
    q = select(Event).where(Event.id > last_id, Event.order_id.is_not(None))
    if order_id is not None:
        q = q.where(Event.order_id == order_id)
    return list(session.scalars(q.order_by(Event.id).limit(limit)))
