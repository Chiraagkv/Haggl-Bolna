"""HTTP routes for Phase 1: the Bolna webhook, the submit_quote tool, and debug views."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import orchestrator, services
from app.config import get_settings
from app.db import get_session
from app.models import Call, Event, Quote

log = logging.getLogger("dalaal")
router = APIRouter()


def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


# ------------------------------------------------------------------------- webhook
@router.post("/webhook/bolna")
async def bolna_webhook(request: Request, session: Session = Depends(get_session)) -> dict:
    """Receive a Bolna status webhook.

    Order of operations matters (ticket #8): store the raw payload FIRST, then process, then
    answer 200. A slow or failing handler makes Bolna retry and produce duplicates, so
    processing errors are logged and swallowed; the raw event can be replayed.
    """
    s = get_settings()
    ip = client_ip(request)
    if s.enforce_webhook_ips and ip not in s.allowed_ips:
        raise HTTPException(status_code=403, detail="source not allowed")

    body = await request.body()
    text = body.decode("utf-8", errors="replace")
    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError:
        payload = None

    execution_id = None
    if isinstance(payload, dict):
        execution_id = payload.get("id") or payload.get("execution_id")
    services.log_event(session, "webhook", payload=payload, raw_text=text if payload is None else None,
                       execution_id=execution_id, source_ip=ip)

    if isinstance(payload, dict):
        try:
            orchestrator.process_webhook(session, payload)
        except Exception:  # noqa: BLE001
            session.rollback()
            log.exception("webhook processing failed; raw event is stored and can be replayed")
    return {"ok": True}


# -------------------------------------------------------------------- submit_quote
def _check_secret(request: Request) -> None:
    secret = get_settings().tool_secret
    if secret and request.headers.get("x-dalaal-token") != secret:
        raise HTTPException(status_code=401, detail="bad token")


def _handle_quote(session: Session, data: dict, ip: str | None) -> dict:
    services.log_event(session, "tool", payload=data, execution_id=data.get("execution_id"), source_ip=ip)
    if not data.get("item"):
        raise HTTPException(status_code=422, detail="item is required")
    call_ref = data.get("call_ref") or None
    execution_id = data.get("execution_id") or None
    if not call_ref and not execution_id:
        raise HTTPException(status_code=422, detail="call_ref or execution_id is required")
    q = orchestrator.process_tool_quote(session, data)
    return {
        "ok": True,
        "stored": q is not None,
        "provisional": bool(q.provisional) if q else None,
        "flagged": bool(q.flagged) if q else None,
        # The reply goes back to the voice agent's LLM, so keep it short and plain.
        "message": "recorded",
    }


@router.post("/tools/submit_quote")
async def submit_quote_post(request: Request, session: Session = Depends(get_session)) -> dict:
    _check_secret(request)
    try:
        data = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="body must be JSON") from None
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="body must be a JSON object")
    return _handle_quote(session, data, client_ip(request))


@router.get("/tools/submit_quote")
def submit_quote_get(request: Request, session: Session = Depends(get_session)) -> dict:
    """Bolna's docs sample uses GET; accept query parameters too until #11 shows which it sends."""
    _check_secret(request)
    return _handle_quote(session, dict(request.query_params), client_ip(request))


# ------------------------------------------------------------------------- debug
@router.get("/debug/calls")
def debug_calls(session: Session = Depends(get_session)) -> list[dict]:
    """Calls with their quotes. Watch this while a teammate speaks to see `submit_quote` land."""
    out = []
    for c in session.scalars(select(Call).order_by(Call.id.desc()).limit(50)):
        quotes = session.scalars(select(Quote).where(Quote.call_id == c.id)).all()
        out.append(
            {
                "call_id": c.id,
                "call_ref": c.call_ref,
                "execution_id": c.execution_id,
                "status": c.status,
                "duration": c.duration,
                "cost": c.cost,
                "quotes": [
                    {
                        "item": q.item,
                        "unit_price": q.unit_price,
                        "unit": q.unit,
                        "price_per_base": q.price_per_base,
                        "base_unit": q.base_unit,
                        "flagged": q.flagged,
                        "flag_reason": q.flag_reason,
                        "provisional": q.provisional,
                        "source": q.source,
                        "credit_days": q.credit_days,
                        "delivery_fee": q.delivery_fee,
                        "delivery_time": q.delivery_time,
                        "raw_text": q.raw_text,
                    }
                    for q in quotes
                ],
            }
        )
    return out


@router.get("/debug/events")
def debug_events(limit: int = 30, session: Session = Depends(get_session)) -> list[dict]:
    """Raw events, newest first. The first real webhook here tells you Bolna's true payload shape."""
    rows = session.scalars(select(Event).order_by(Event.id.desc()).limit(max(1, min(limit, 200))))
    return [
        {"id": e.id, "kind": e.kind, "execution_id": e.execution_id, "ip": e.source_ip,
         "payload": e.payload, "raw_text": e.raw_text, "at": e.created_at.isoformat()}
        for e in rows
    ]
