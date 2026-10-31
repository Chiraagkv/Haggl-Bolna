"""Call and quote handling. All writes are idempotent (ticket #9) and quotes follow the
provisional -> confirmed rule from the Bible (ticket #11 / edge cases 15 and 16).

Rules:
  * A call row is unique by execution_id (and by our call_ref). Duplicates change nothing.
  * Status only moves forward. A late `ringing` after `completed` is ignored. This is done
    with a conditional UPDATE, so two simultaneous webhooks cannot both win.
  * Data (transcript, cost, extraction) is filled only where still empty.
  * A quote from the live tool is PROVISIONAL. The extraction at `completed` confirms it and
    overwrites it. A confirmed quote is never overwritten by a late tool call.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import parsing, reference, statuses
from app.models import Call, Event, Quote


# ----------------------------------------------------------------------------- events
def log_event(
    session: Session,
    kind: str,
    payload: Any = None,
    raw_text: str | None = None,
    execution_id: str | None = None,
    source_ip: str | None = None,
) -> Event:
    """Write the raw event first and commit, before any processing can fail."""
    ev = Event(kind=kind, payload=payload, raw_text=raw_text, execution_id=execution_id, source_ip=source_ip)
    session.add(ev)
    session.commit()
    return ev


# ------------------------------------------------------------------------------ calls
def find_call(session: Session, call_ref: str | None = None, execution_id: str | None = None) -> Call | None:
    if execution_id:
        call = session.scalar(select(Call).where(Call.execution_id == execution_id))
        if call:
            return call
    if call_ref:
        return session.scalar(select(Call).where(Call.call_ref == call_ref))
    return None


def get_or_create_call(
    session: Session,
    call_ref: str | None = None,
    execution_id: str | None = None,
    **fields: Any,
) -> Call:
    """Find the call by execution_id or call_ref, or create it. Safe under races."""
    if not call_ref and not execution_id:
        raise ValueError("need a call_ref or an execution_id")
    call = find_call(session, call_ref, execution_id)
    if call:
        # learn the missing half of the pair, without ever overwriting a different value
        changed = False
        if execution_id and not call.execution_id:
            call.execution_id = execution_id
            changed = True
        if call_ref and not call.call_ref:
            call.call_ref = call_ref
            changed = True
        if changed:
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                call = find_call(session, call_ref, execution_id)
                assert call is not None
        return call
    call = Call(call_ref=call_ref, execution_id=execution_id, **fields)
    session.add(call)
    try:
        session.commit()
    except IntegrityError:  # another request created it first
        session.rollback()
        found = find_call(session, call_ref, execution_id)
        assert found is not None
        return found
    return call


def _to_float(v: Any) -> float | None:
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def apply_webhook(session: Session, payload: dict) -> dict:
    """Apply one Bolna status webhook. Returns a small summary (useful for tests and logs).

    The payload has the same structure as GET /executions/{id}: `id`, `status`, `transcript`,
    `extracted_data`, `conversation_duration`, `total_cost`, `telephony_data.recording_url`,
    `answered_by_voice_mail`, `context_details`.
    """
    execution_id = payload.get("id") or payload.get("execution_id")
    ctx = payload.get("context_details") or {}
    call_ref = ctx.get("call_ref") if isinstance(ctx, dict) else None
    if not execution_id and not call_ref:
        return {"ok": False, "reason": "no execution id"}

    call = get_or_create_call(session, call_ref=call_ref, execution_id=execution_id)
    result = {"ok": True, "call_id": call.id, "advanced": False, "quotes": 0}

    status = (payload.get("status") or "").strip().lower() or None
    new_rank = statuses.rank(status)
    if new_rank is not None:
        res = session.execute(
            update(Call)
            .where(Call.id == call.id, Call.status_rank < new_rank)
            .values(status=status, status_rank=new_rank)
        )
        session.commit()
        result["advanced"] = res.rowcount == 1

    # The transcript is already final at `call-disconnected` (seen live: same text, ~14 s before
    # `completed`), so show it early. Everything else is only trustworthy once the call is `completed`.
    if status == "call-disconnected" and payload.get("transcript"):
        session.execute(update(Call).where(Call.id == call.id, Call.transcript.is_(None)).values(transcript=payload["transcript"]))
        session.commit()
    if status == "completed":
        telephony = payload.get("telephony_data") or {}
        fills = {
            "duration": _to_float(payload.get("conversation_duration")),
            "cost": _to_float(payload.get("total_cost")),
            "transcript": payload.get("transcript"),
            "recording_url": telephony.get("recording_url") if isinstance(telephony, dict) else None,
            "extracted_data": payload.get("extracted_data"),
            "answered_by_voicemail": payload.get("answered_by_voice_mail"),
        }
        for column, value in fills.items():
            if value is None:
                continue
            col = getattr(Call, column)
            # The first `completed` transcript replaces the early one from `call-disconnected`; replays change nothing.
            guard = Call.completed_at.is_(None) if column == "transcript" else col.is_(None)
            session.execute(update(Call).where(Call.id == call.id, guard).values({column: value}))
        session.execute(
            update(Call).where(Call.id == call.id, Call.completed_at.is_(None)).values(completed_at=datetime.now(timezone.utc))
        )
        session.commit()

        extracted = payload.get("extracted_data")
        for q in quotes_from_extracted_data(extracted):
            upsert_quote(session, call, q, source="extraction", provisional=False)
            result["quotes"] += 1
    return result


# ---------------------------------------------------------------------------- quotes
def _strip_fences(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    return t.strip()


def quotes_from_extracted_data(extracted: Any) -> list[dict]:
    """Pull quote dicts out of Bolna's `extracted_data`.

    extracted_data is nested {category: {extraction_name: {subjective, objective, ...}}}.
    We define ONE free-text extraction called `quotes_json` whose answer is a JSON list:
        [{"item": "onions", "unit_price": "25", "unit": "kg", "available": true,
          "delivery_time": "07:00", "credit_days": 0, "delivery_fee": 0, "what_they_said": "..."}]
    UNVERIFIED against a live call: ticket #10 confirms the real shape. If it differs, the raw
    payload is already in `events`, so nothing is lost.
    """
    if not isinstance(extracted, dict):
        return []
    answer: str | None = None
    for category in extracted.values():
        if isinstance(category, dict) and isinstance(category.get("quotes_json"), dict):
            answer = category["quotes_json"].get("subjective")
            break
    if not answer or not isinstance(answer, str):
        return []
    try:
        data = json.loads(_strip_fences(answer))
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = data.get("quotes", [data])
    return [d for d in data if isinstance(d, dict) and d.get("item")] if isinstance(data, list) else []


def normalise_quote(raw: dict) -> dict:
    """Turn a loosely-typed quote (from the tool or the extraction) into column values."""
    item = str(raw.get("item", "")).strip().lower()
    price_in = raw.get("unit_price")
    unit_in = raw.get("unit")

    amount: float | None = None
    price_text = ""
    if isinstance(price_in, (int, float)):
        amount = float(price_in)
    elif isinstance(price_in, str):
        price_text = price_in
        amount = parsing.parse_number(price_in)

    flagged = False
    reason: str | None = None
    unit_canonical = None
    base_unit = None
    per_base = None

    avail_in = raw.get("available")
    said_unavailable = avail_in is False or (isinstance(avail_in, str) and avail_in.strip().lower() in {"false", "no", "nahi"})
    if amount is None:
        if not said_unavailable:  # "not available" is a real answer, not a parsing problem
            flagged, reason = True, "no price"
    else:
        # Prefer a unit stated in the price text, then the separate unit field.
        parsed = parsing.parse_price(f"{price_text} {unit_in or ''}".strip() if price_text else f"{amount} rupaye {unit_in or ''}")
        unit_canonical = parsed.unit
        base_unit = parsed.base_unit
        per_base = parsed.price_per_base
        if parsed.flagged:
            flagged, reason = True, parsed.reason

    avail = raw.get("available")
    if isinstance(avail, str):
        avail = avail.strip().lower() in {"true", "yes", "haan", "ha", "1"}

    credit = raw.get("credit_days")
    return {
        "item": item,
        "unit_price": amount,
        "unit": unit_canonical,
        "base_unit": base_unit,
        "price_per_base": per_base,
        "flagged": flagged,
        "flag_reason": reason,
        "available": avail if isinstance(avail, bool) else None,
        "delivery_time": (str(raw["delivery_time"]) if raw.get("delivery_time") is not None else None),
        "credit_days": int(parsing.parse_number(str(credit)) or 0) if credit not in (None, "") else None,
        "delivery_fee": _to_float(raw.get("delivery_fee")),
        "raw_text": raw.get("what_they_said") or raw.get("raw_text"),
    }


def upsert_quote(session: Session, call: Call, raw: dict, source: str, provisional: bool) -> Quote | None:
    """Insert or update the single quote for (call, item).

    * New row: insert.
    * Existing provisional row + incoming confirmed: overwrite with the confirmed values.
    * Existing provisional row + incoming provisional: update (the supplier corrected himself).
    * Existing confirmed row + incoming anything: leave it alone (idempotent).
    """
    values = normalise_quote(raw)
    if not values["item"]:
        return None
    values["mandi_flag"] = reference.check(values["item"], values["price_per_base"], values["base_unit"])
    existing = session.scalar(select(Quote).where(Quote.call_id == call.id, Quote.item == values["item"]))
    if existing is None:
        q = Quote(call_id=call.id, provisional=provisional, source=source, **values)
        session.add(q)
        try:
            session.commit()
        except IntegrityError:  # lost a race: fall through to the update path
            session.rollback()
            existing = session.scalar(select(Quote).where(Quote.call_id == call.id, Quote.item == values["item"]))
        else:
            return q
    if existing is None:
        return None
    if not existing.provisional:
        return existing  # confirmed values are final
    for k, v in values.items():
        setattr(existing, k, v)
    existing.provisional = provisional
    existing.source = source
    session.commit()
    return existing


def quote_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Quote)) or 0


# ------------------------------------------------------------------ tool quote + extractions
def record_tool_quote(session: Session, data: dict) -> Quote | None:
    """A quote from the live submit_quote tool (provisional). Shared by the route and the fake provider."""
    call_ref = data.get("call_ref") or None
    execution_id = data.get("execution_id") or None
    call = get_or_create_call(session, call_ref=call_ref, execution_id=execution_id)
    return upsert_quote(session, call, data, source="submit_quote", provisional=True)


def extraction_value(extracted: Any, name: str) -> Any:
    """The parsed answer of a named extraction (`approval`, `confirmed`, `order_json`, ...).

    Same nesting as quotes_json: {category: {name: {subjective: "<text or JSON>"}}}. JSON text is
    parsed; anything else comes back as the plain string. None if absent.
    """
    if not isinstance(extracted, dict):
        return None
    for category in extracted.values():
        if isinstance(category, dict) and isinstance(category.get(name), dict):
            ans = category[name].get("subjective")
            if ans is None:
                ans = category[name].get("objective")
            if isinstance(ans, str):
                try:
                    return json.loads(_strip_fences(ans))
                except json.JSONDecodeError:
                    return ans.strip()
            return ans
    return None


# ------------------------------------------------------------------ reading answers
# Bolna's extractor does not always obey "Return ONLY JSON": seen live, the `confirmed` answer came back as
# "Yes, the supplier confirmed 10 litres of oil ... for a total of 900 rupees". So yes/no and number answers
# are read leniently from whatever shape arrives: a bool, JSON, one word, or a whole sentence.
_YES_WORDS = {"yes", "y", "haan", "han", "ha", "haa", "ji", "true", "ok", "okay", "approved", "approve", "confirmed",
              "confirm", "book", "agreed", "sure", "हाँ", "हां", "हा", "जी", "ಹೌದು"}
_NO_WORDS = {"no", "n", "nahi", "nahin", "nahii", "na", "false", "not", "declined", "decline", "refused", "never",
             "नहीं", "नही", "ना", "ಇಲ್ಲ"}


def yes_no(value: Any) -> bool | None:
    """True for a clear yes, False for a clear no, None when absent or unclear ("unclear", "maybe", empty)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, dict):
        for key in ("decision", "confirmed", "answer", "value"):
            if key in value:
                return yes_no(value[key])
        return None
    if isinstance(value, str):
        words = [w for w in re.split(r"[\s,.;:!?\"'()\[\]\-]+", value.strip().lower()) if w]
        if not words:
            return None
        if words[0] in _YES_WORDS:
            return True
        if words[0] in _NO_WORDS:
            return False
    return None


def number(value: Any) -> float | None:
    """The first number in an answer ("900", 900, "Rs 1,100 total", "९००"); None if there is none."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"\d+(?:\.\d+)?", parsing.normalise_digits(str(value)).replace(",", ""))
    return float(m.group(0)) if m else None
