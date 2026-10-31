"""Product API and dashboard feed (tickets #31, #37-#40, #44)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import metrics, orchestrator, orders, preflight, providers, seed, services
from app.config import get_settings
from app.db import get_session
from app.models import Call, Event, Order, Owner, Quote, Supplier

router = APIRouter()
STATIC = Path(__file__).resolve().parent / "static"


class ItemIn(BaseModel):
    name: str
    quantity: float
    unit: str


class OrderIn(BaseModel):
    owner_id: int | None = None
    items: list[ItemIn]
    deadline: str
    budget: float | None = None
    start: bool = True


def _owner_id(session: Session, given: int | None) -> int:
    if given:
        return given
    o = session.scalar(select(Owner).order_by(Owner.id))
    if o is None:
        raise HTTPException(409, "no owner yet: run `python scripts/seed_demo.py` or POST /api/demo/start (fake mode)")
    return o.id


@router.post("/api/orders")
def create_order(body: OrderIn, session: Session = Depends(get_session)) -> dict:
    try:
        order = orchestrator.create_order(session, _owner_id(session, body.owner_id), [i.model_dump() for i in body.items],
                                          body.deadline, body.budget)
    except orchestrator.OrderInvalid as e:
        raise HTTPException(422, str(e)) from None
    started = orchestrator.start_order(session, order.id) if body.start else False
    return {"order_id": order.id, "started": started}


@router.get("/api/setup")
def setup(session: Session = Depends(get_session)) -> dict:
    """What the order form needs: who the owner is, which suppliers exist, what they sell and whether
    they can be dialed right now, plus the demo order to pre-fill."""
    s = get_settings()
    owner = seed.ensure_demo_data(session) if s.provider == "fake" else session.scalar(select(Owner).order_by(Owner.id))
    if owner is None:
        raise HTTPException(409, "no owner yet: run `python scripts/go_live.py owner=+91... kumar=+91...`")
    probe = Order(owner_id=owner.id, items=[{"name": i} for i in _known_items(session, owner.id)])
    callable_keys = {x.key for x in orchestrator.select_suppliers(session, probe, s)}
    sups = list(session.scalars(select(Supplier).where(Supplier.owner_id == owner.id).order_by(Supplier.id)))
    return {
        "provider": s.provider, "owner": {"id": owner.id, "name": owner.name, "business_name": owner.business_name},
        "suppliers": [{"key": x.key, "name": x.name, "items": x.items or [], "callable": x.key in callable_keys,
                       "language": x.language} for x in sups],
        "known_items": _known_items(session, owner.id),
        "demo_order": seed.demo_order_spec(), "concurrency_limit": s.concurrency_limit,
        "estimated_cost_per_call_inr": s.estimated_cost_per_call_inr,
    }


def _known_items(session: Session, owner_id: int) -> list[str]:
    return sorted({i.lower() for x in session.scalars(select(Supplier).where(Supplier.owner_id == owner_id)) for i in (x.items or [])})


@router.post("/api/orders/preview")
def preview(body: OrderIn, session: Session = Depends(get_session)) -> dict:
    """Who would be called, in which pairs, and roughly what it costs. Nothing is saved or dialed."""
    s = get_settings()
    try:
        items = orchestrator.normalise_items([i.model_dump() for i in body.items], s)
        orchestrator.normalise_deadline(body.deadline)
    except orchestrator.OrderInvalid as e:
        raise HTTPException(422, str(e)) from None
    order = Order(owner_id=_owner_id(session, body.owner_id), items=items)
    sups = orchestrator.select_suppliers(session, order, s)
    wanted = {i["name"] for i in items}
    waves = orchestrator.plan_round1_waves(wanted, sups, s.concurrency_limit)
    covered = set().union(*(orchestrator._covers(x, wanted) for x in sups)) if sups else set()
    return {
        "waves": [[{"key": x.key, "name": x.name, "sells": sorted(orchestrator._covers(x, wanted))} for x in w] for w in waves],
        "uncovered": sorted(wanted - covered),
        "estimated_cost_inr": orchestrator.estimated_order_cost_inr(len(sups), s),
    }


@router.post("/api/orders/{order_id}/start")
def start(order_id: int, session: Session = Depends(get_session)) -> dict:
    if session.get(Order, order_id) is None:
        raise HTTPException(404, "no such order")
    return {"started": orchestrator.start_order(session, order_id)}


@router.post("/api/intake/call")
def intake_call(owner_id: int | None = None, session: Session = Depends(get_session)) -> dict:
    """Ring the owner with the intake agent; what they say becomes an order and starts automatically."""
    try:
        call = orchestrator.plan_intake_call(session, _owner_id(session, owner_id))
    except orchestrator.OrderInvalid as e:
        raise HTTPException(409, str(e)) from None
    return {"call_id": call.id, "note": "dispatched on the next tick (a few seconds)"}


@router.post("/api/tick")
def manual_tick(session: Session = Depends(get_session)) -> dict:
    p = providers.get_provider()
    r = orchestrator.tick(session)
    r["delivered"] = p.pump(session)
    return r


@router.post("/api/orders/{order_id}/kill")
def kill(order_id: int, session: Session = Depends(get_session)) -> dict:
    """Stop one order now (the dashboard's emergency button). Pending calls are cancelled."""
    return {"failed": orchestrator._fail(session, order_id, "stopped_by_operator")}


# Bolna's own reason a call ended (`termination_reason` in the webhook), in words for the board.
ENDED = {"user_hung_up": "they hung up", "inactivity_timeout": "ended after silence", "max_duration_reached": "hit the time limit",
         "agent_hung_up": "the agent ended it", "call_ended_by_agent": "the agent ended it"}


def _ended_because(session: Session, calls: list[Call]) -> dict[str, str]:
    """execution_id -> why Bolna says the call ended (from the stored webhooks; the Call table has no column for it)."""
    ids = [c.execution_id for c in calls if c.execution_id and c.status_rank >= 5]
    out: dict[str, str] = {}
    if not ids:
        return out
    for e in session.scalars(select(Event).where(Event.kind == "webhook", Event.execution_id.in_(ids)).order_by(Event.id)):
        reason = (e.payload or {}).get("termination_reason") if isinstance(e.payload, dict) else None
        if reason:
            out[e.execution_id] = ENDED.get(reason, str(reason).replace("_", " "))  # type: ignore[index]
    return out


def snapshot(session: Session, order_id: int) -> dict:
    o = orders.get_order(session, order_id)
    if o is None:
        raise HTTPException(404, "no such order")
    calls = list(session.scalars(select(Call).where(Call.order_id == order_id).order_by(Call.id)))
    cmap = {c.id: c for c in calls}
    quotes = [q for q in session.scalars(select(Quote).where(Quote.call_id.in_(list(cmap) or [0])).order_by(Quote.id))]
    evs = orders.events_after(session, order_id, 0, 5000)
    ended = _ended_because(session, calls)
    return {
        "order": {
            "id": o.id, "state": o.state, "items": o.items, "deadline": o.deadline, "budget": o.budget,
            "assignments": o.assignments, "booked_total": o.booked_total, "savings": o.savings,
            "baseline_total": o.baseline_total, "baseline_kind": o.baseline_kind, "time_saved_min": o.time_saved_min,
            "cost_incurred": o.cost_incurred, "failure_reason": o.failure_reason, "approval": o.approval,
            "booking_attempts": o.booking_attempts,
        },
        "calls": [{"id": c.id, "kind": c.kind, "supplier": c.supplier_key, "round": c.round, "status": c.status,
                   "duration": c.duration, "cost": c.cost, "voicemail": c.answered_by_voicemail,
                   "transcript": c.transcript, "wave": (c.user_data or {}).get("wave"),
                   "anchors": (c.user_data or {}).get("anchors") or [],
                   "counter": (c.user_data or {}).get("counter") or [],
                   "placed_at": c.placed_at.isoformat() if c.placed_at else None,
                   "completed_at": c.completed_at.isoformat() if c.completed_at else None,
                   "ended_because": ended.get(c.execution_id or "")} for c in calls],
        "quotes": [{"supplier": cmap[q.call_id].supplier_key, "round": cmap[q.call_id].round, "item": q.item,
                    "price": q.unit_price, "unit": q.unit, "per_base": q.price_per_base, "available": q.available,
                    "provisional": q.provisional, "flagged": q.flagged, "flag_reason": q.flag_reason, "mandi_flag": q.mandi_flag,
                    "credit_days": q.credit_days, "delivery_time": q.delivery_time, "said": q.raw_text} for q in quotes],
        "receipt": receipt(session, o, calls),
        "ranking": o.ranking,
        "suppliers": {s.key: {"name": s.name, "on_time": s.on_time_count, "late": s.late_count}
                      for s in session.scalars(select(Supplier).where(Supplier.owner_id == o.owner_id))},
        "last_event_id": evs[-1].id if evs else 0,
        "feed": [{"id": e.id, "type": e.kind, "payload": e.payload, "at": e.created_at.isoformat()} for e in evs[-60:]],
    }


def receipt(session: Session, o: Order, calls: list[Call]) -> dict | None:
    """The bill, once booked: exactly what each supplier agreed to on the confirmation call."""
    if o.state not in (orders.BOOKED, orders.REPORTED):
        return None
    snap = o.ranking or {}
    parts = (snap.get("decision") or {}).get("per_supplier") or []
    ranked = {r["key"]: r for r in snap.get("ranked") or []}
    owner = session.get(Owner, o.owner_id)
    out = []
    for p in parts:
        key = p["key"]
        confirm = next((c for c in reversed(calls) if c.kind == "confirm" and c.supplier_key == key and c.status == "completed"), None)
        data = (confirm.user_data or {}) if confirm else {}
        said = services.extraction_value(confirm.extracted_data, "confirmed") if confirm else None
        if confirm and not isinstance(said, dict):  # the separate-answers shape (bolna/extractions.json)
            when = services.extraction_value(confirm.extracted_data, "confirm_delivery_time")
            said = {"delivery_time": when} if when and str(when).strip().lower() not in ("none", "0", "") else None
        lines = [{"item": a["item"], "quantity": a["quantity"], "unit": a["unit"], "unit_price": a["price"],
                  "amount": round(a["quantity"] * a["price"], 2)} for a in data.get("agreed") or []]
        out.append({
            "key": key, "name": p["name"], "lines": lines, "delivery_fee": p.get("delivery_fee") or 0,
            "subtotal": round(sum(x["amount"] for x in lines) + (p.get("delivery_fee") or 0), 2),
            "delivery_time": (said.get("delivery_time") if isinstance(said, dict) and said.get("delivery_time") else None)
                             or data.get("delivery_time"),
            "credit_days": (ranked.get(key) or {}).get("credit_days") or 0,
            "confirmed_on_call": confirm.id if confirm else None,
        })
    return {
        "order_no": f"DAL-{o.id:04d}", "date": (o.finished_at or o.updated_at or o.created_at).isoformat(),
        "business_name": owner.business_name if owner else "", "owner": owner.name if owner else "",
        "deadline": o.deadline, "suppliers": out, "total": o.booked_total, "baseline": o.baseline_total,
        "baseline_kind": o.baseline_kind, "savings": o.savings, "call_cost": o.cost_incurred,
        "time_saved_min": o.time_saved_min, "approved_by_owner": (o.approval or {}).get("status") == "approved",
        "calls_made": sum(1 for c in calls if c.status_rank >= 1),
    }


@router.get("/api/orders/{order_id}/state")
def state(order_id: int, session: Session = Depends(get_session)) -> dict:
    return snapshot(session, order_id)


@router.get("/api/orders")
def list_orders(session: Session = Depends(get_session)) -> list[dict]:
    return [{"id": o.id, "state": o.state, "created_at": o.created_at.isoformat(), "booked_total": o.booked_total,
             "savings": o.savings, "failure_reason": o.failure_reason}
            for o in session.scalars(select(Order).order_by(Order.id.desc()).limit(30))]


@router.get("/api/orders/{order_id}/stream")
async def stream(order_id: int, request: Request, last: int = 0):
    """Server-sent events. A reconnecting browser sends Last-Event-ID and misses nothing, because the
    feed is read from the database, not from memory."""
    cursor = int(request.headers.get("last-event-id") or last or 0)

    async def gen():
        nonlocal cursor
        idle = 0
        while not await request.is_disconnected():
            def read():
                sess = next(get_session())
                try:
                    return [(e.id, e.kind, e.payload) for e in orders.events_after(sess, order_id, cursor, 100)]
                finally:
                    sess.close()
            rows = await asyncio.to_thread(read)
            for eid, kind, payload in rows:
                cursor = eid
                yield f"id: {eid}\nevent: {kind}\ndata: {json.dumps(payload or {}, ensure_ascii=False)}\n\n"
            idle = 0 if rows else idle + 1
            if idle % 10 == 9:
                yield ": keepalive\n\n"
            await asyncio.sleep(0.7)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class DeliveryIn(BaseModel):
    supplier_key: str
    on_time: bool


@router.post("/api/deliveries")
def record_delivery(body: DeliveryIn, session: Session = Depends(get_session)) -> dict:
    """Feeds the reliability score. In the demo the history is typed in; in real use the owner reports it."""
    sup = session.scalar(select(Supplier).where(Supplier.key == body.supplier_key))
    if sup is None:
        raise HTTPException(404, "no such supplier")
    if body.on_time:
        sup.on_time_count += 1
    else:
        sup.late_count += 1
    session.commit()
    return {"on_time": sup.on_time_count, "late": sup.late_count}


@router.post("/api/demo/start")
def demo_start(session: Session = Depends(get_session)) -> dict:
    """One click: seed Priya and her suppliers, place the demo order, start it. Fake provider only."""
    s = get_settings()
    if s.provider != "fake":
        raise HTTPException(409, "demo/start only runs with PROVIDER=fake (it would otherwise phone real numbers)")
    owner = seed.ensure_demo_data(session)
    live = [o for o in session.scalars(select(Order).where(Order.owner_id == owner.id)) if orders.is_live(o.state)]
    for o in live:
        orchestrator._fail(session, o.id, "superseded_by_new_demo")
    spec = seed.demo_order_spec()
    order = orchestrator.create_order(session, owner.id, spec["items"], spec["deadline"], spec["budget"])
    return {"order_id": order.id, "started": orchestrator.start_order(session, order.id)}


@router.get("/api/preflight")
def get_preflight(probe: bool = False, session: Session = Depends(get_session)) -> dict:
    return preflight.run(session, get_settings(), probe)


@router.get("/api/metrics")
def get_metrics(session: Session = Depends(get_session)) -> dict:
    return metrics.compute(session)


@router.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return (STATIC / "dashboard.html").read_text(encoding="utf-8")
