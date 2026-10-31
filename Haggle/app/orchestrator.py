"""The conductor (tickets #19-#23, #31-#36).

One idempotent `tick()` moves every live order forward as far as the data allows. It is driven by
three things, any of which may fire at any time: a Bolna webhook, the background loop, and the
manual endpoint. It is safe because (a) the database is the only source of truth, (b) every state
change is a conditional UPDATE (see orders.transition), and (c) a process-wide lock serialises ticks.

Flow:  DRAFT -> COLLECTING_R1 -> RANKED -> NEGOTIATING_R2 -> RERANKED -> [AWAITING_APPROVAL]
       -> BOOKING -> BOOKED -> REPORTED          (any state -> FAILED, with a reason)

Safety rules enforced here, not in prompts:
  * calls are planned as `pending` rows and dialed only when guards + concurrency allow;
  * round 1 runs in waves the size of the concurrency limit (pairs on a trial account), each wave
    grouping suppliers who sell the same items; a later wave hears the best price already confirmed
    by earlier waves, so it can bargain live (still real prices only: negotiation.assert_real_anchors);
  * round-2 counter-offers may only cite real quotes (negotiation.assert_real_offers);
  * an order over budget, partial, or relying on unconfirmed quotes is never booked without a "yes";
  * a booking is accepted only if the confirmation matches the quantities (and roughly the total);
  * if a confirmation fails, the runner-up is tried; the cap is MAX_BOOKING_ATTEMPTS.
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import bolna_setup, guards, negotiation, notifier, orders, parsing, ranking, savings, services, statuses
from app import providers as providers_mod
from app.config import Settings, get_settings
from app.models import Call, Order, Owner, Quote, Supplier

log = logging.getLogger("dalaal.orchestrator")
LOCK = threading.RLock()
MAX_R1_SUPPLIERS = 4
OWNER_KINDS = ("approval", "callback", "intake")
YES = {"yes", "y", "haan", "ha", "han", "ji", "ok", "okay", "approved", "approve", "true", "book", "kar do"}


class OrderInvalid(ValueError):
    pass


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; they are UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ============================================================================ speaking
def speak_clock(hhmm: str) -> str:
    m = ranking.parse_clock(hhmm)
    if m is None:
        return hhmm
    h, mi = divmod(m, 60)
    part = "subah" if h < 12 else ("dopahar" if h < 16 else "shaam")
    h12 = h if 1 <= h <= 12 else (h - 12 if h > 12 else 12)
    return f"{part} {h12} baje" if mi == 0 else f"{part} {h12}:{mi:02d} baje"


def _unit_word(unit: str) -> str:
    return {"kg": "kilo", "litre": "litre", "piece": "piece", "gram": "gram", "dozen": "dozen", "quintal": "quintal"}.get(unit, unit)


def speak_items(items: list[dict]) -> str:
    return ", ".join(f"{negotiation.number_text(float(i['quantity']))} {_unit_word(parsing.normalise_unit(i['unit']).base if parsing.normalise_unit(i['unit']) else i['unit'])} {i['name']}" for i in items)


def inr(x: float) -> str:
    return f"Rs {x:,.0f}"


# ================================================================== order creation
def normalise_items(raw: list[dict], s: Settings) -> list[dict]:
    if not raw:
        raise OrderInvalid("the order has no items")
    out = []
    for it in raw:
        name = str(it.get("name", "")).strip().lower()
        if not name:
            raise OrderInvalid("an item has no name")
        try:
            qty = float(it.get("quantity"))
        except (TypeError, ValueError):
            raise OrderInvalid(f"{name}: quantity is not a number") from None
        if qty <= 0:
            raise OrderInvalid(f"{name}: quantity must be positive")
        u = parsing.normalise_unit(str(it.get("unit", "")))
        if u is None or u.to_base is None:
            raise OrderInvalid(f"{name}: unknown unit {it.get('unit')!r}")
        if qty * u.to_base > s.max_quantity_per_item * 1.0 and u.base in ("kg", "litre", "piece"):
            raise OrderInvalid(f"{name}: {qty:g} {it.get('unit')} is above the sanity limit ({s.max_quantity_per_item:g})")
        out.append({"name": name, "quantity": qty, "unit": u.base if u.base else str(it.get("unit"))})
    return out


def normalise_deadline(text: Any) -> str:
    m = ranking.parse_clock(str(text) if text is not None else None)
    if m is None:
        raise OrderInvalid(f"cannot read the deadline {text!r}")
    return f"{m // 60:02d}:{m % 60:02d}"


def create_order(session: Session, owner_id: int, items: list[dict], deadline: Any, budget: float | None = None,
                 settings: Settings | None = None) -> Order:
    s = settings or get_settings()
    owner = session.get(Owner, owner_id)
    if owner is None:
        raise OrderInvalid(f"no owner {owner_id}")
    norm = normalise_items(items, s)
    dl = normalise_deadline(deadline)
    base = savings.baseline_from_owner_prices(ranking.order_lines(norm), owner.usual_prices)
    order = Order(owner_id=owner_id, items=norm, deadline=dl, budget=float(budget) if budget not in (None, "") else None,
                  baseline_total=base.total if base else None, baseline_kind=base.kind if base else None)
    session.add(order)
    session.commit()
    orders.emit(session, order.id, "created", {"items": norm, "deadline": dl, "budget": order.budget})
    return order


# ================================================================== planning calls
def _new_ref(order_id: int, kind: str, who: str) -> str:
    return f"o{order_id}-{kind}-{who}-{uuid.uuid4().hex[:6]}"


def plan_call(session: Session, order: Order, kind: str, to_number: str, user_data: dict, *, supplier_key: str | None = None,
              round_: int | None = None) -> Call:
    ref = _new_ref(order.id, kind, supplier_key or "owner")
    who = _suppliers_by_key(session, order).get(supplier_key) if supplier_key else _owner(session, order)
    # Bolna starts the call in this language (multilingual agents) and still switches if the person does.
    lang = bolna_setup.call_language(who.language if who is not None else None)
    data = {**user_data, "call_ref": ref, "kind": kind, "supplier_key": supplier_key or "", "agent_language": lang}
    call = Call(call_ref=ref, order_id=order.id, supplier_key=supplier_key, round=round_, kind=kind, to_number=to_number,
                user_data=data, status="pending", status_rank=-1)
    session.add(call)
    session.commit()
    orders.emit(session, order.id, "call_planned", {"call_id": call.id, "kind": kind, "supplier": supplier_key, "round": round_})
    return call


def _owner(session: Session, order: Order) -> Owner:
    o = session.get(Owner, order.owner_id)
    assert o is not None
    return o


def _owner_phone(owner: Owner, s: Settings) -> str | None:
    return s.owner_phone_override or owner.phone


def _suppliers_by_key(session: Session, order: Order) -> dict[str, Supplier]:
    return {x.key: x for x in session.scalars(select(Supplier).where(Supplier.owner_id == order.owner_id))}


def _covers(sup: Supplier, wanted: set[str]) -> set[str]:
    """What this supplier can quote of the order. No item list means "unknown": assume everything."""
    return wanted & {x.lower() for x in sup.items} if sup.items else set(wanted)


def plan_round1_waves(wanted: set[str], sups: list[Supplier], size: int) -> list[list[Supplier]]:
    """Group round-1 suppliers into waves of `size` (the concurrency limit) by what they sell.

    Greedy: take the supplier who covers the most items, then add the partners who sell the most of
    the same items (identical baskets first). A supplier nobody shares an item with is put into a
    leftover wave at the end, so no call slot is wasted and nobody is dropped.
    """
    covers = {x.key: _covers(x, wanted) for x in sups}
    left = sorted(sups, key=lambda x: (-len(covers[x.key]), x.id))
    waves: list[list[Supplier]] = []
    loners: list[Supplier] = []
    while left:
        group = [left.pop(0)]
        while len(group) < size and left:
            have = set().union(*(covers[g.key] for g in group))
            best = max(left, key=lambda x: (len(covers[x.key] & have), -len(covers[x.key] ^ have), -x.id))
            if not covers[best.key] & have:
                break
            group.append(best)
            left.remove(best)
        if len(group) == 1:
            loners.append(group[0])
        else:
            waves.append(group)
    waves += [loners[i:i + size] for i in range(0, len(loners), size)]
    return waves


def select_suppliers(session: Session, order: Order, settings: Settings | None = None) -> list[Supplier]:
    s = settings or get_settings()
    """Who to ask in round 1: reachable, not on the do-not-call list, and sells something we need."""
    wanted = {i["name"] for i in order.items}
    chosen = []
    for sup in session.scalars(select(Supplier).where(Supplier.owner_id == order.owner_id).order_by(Supplier.id)):
        if sup.do_not_call or not sup.phone:
            continue
        if s.provider == "bolna" and s.require_verified_numbers and sup.phone not in s.verified_number_set:
            continue  # would be refused at dial time; do not waste a slot or a retry on it
        if sup.items and not (wanted & {x.lower() for x in sup.items}):
            continue
        chosen.append(sup)
    return chosen[:MAX_R1_SUPPLIERS]


def estimated_order_cost_inr(n_suppliers: int, s: Settings) -> float:
    """Round 1 + up to two round-2 calls + approval + one confirmation + the callback."""
    return (n_suppliers + 5) * s.estimated_cost_per_call_inr


def start_order(session: Session, order_id: int, settings: Settings | None = None,
                provider: providers_mod.Provider | None = None) -> bool:
    s = settings or get_settings()
    with LOCK:
        order = session.get(Order, order_id)
        if order is None or order.state != orders.DRAFT:
            return False
        try:
            guards.check_can_start_order(session, order.owner_id, order.id, s)
        except guards.GuardRefused as e:
            _fail(session, order.id, f"cannot start: {e}")
            return False
        sups = select_suppliers(session, order, s)
        if not sups:
            _fail(session, order.id, "no_suppliers")
            return False
        need = estimated_order_cost_inr(len(sups), s)
        wallet = (provider or providers_mod.get_provider()).wallet_inr()
        if wallet is not None and wallet < need:
            _fail(session, order.id, f"wallet_too_low: Rs {wallet:,.0f} left, order needs about Rs {need:,.0f}")
            return False
        wanted = {i["name"] for i in order.items}
        waves = plan_round1_waves(wanted, sups, s.concurrency_limit)
        now = now_utc()
        if not orders.transition(session, order.id, orders.COLLECTING_R1, r1_started_at=now,
                                 r1_deadline_at=now + timedelta(seconds=s.round1_deadline_seconds * len(waves))):
            return False
        orders.emit(session, order.id, "round1_waves", {"waves": [[x.key for x in w] for w in waves]})
        for n, wave in enumerate(waves):
            for sup in wave:
                plan_call(session, order, "supplier_r1", sup.phone or "", {
                    "business_name": _owner(session, order).business_name, "items_spoken": speak_items(order.items),
                    "deadline_spoken": speak_clock(order.deadline), "items_list": order.items,
                    "supplier_name": sup.name, "wave": n, "sells": sorted(_covers(sup, wanted)),
                    "competing_quote_spoken": "none"}, supplier_key=sup.key, round_=1)
        return True


# ================================================================== reading quotes
def _usable(q: Quote) -> bool:
    return not q.flagged and q.price_per_base is not None and q.base_unit is not None


def supplier_inputs(session: Session, order: Order, rounds: tuple[int, ...] = (1,), exclude: set[str] | frozenset[str] = frozenset()
                    ) -> tuple[list[ranking.SupplierInput], list[dict]]:
    """Build ranking inputs from stored quotes. Later rounds override earlier ones item by item, but
    never raise a price (a supplier who quoted 25 and then says 26 is held to 25)."""
    sups = _suppliers_by_key(session, order)
    calls = list(session.scalars(select(Call).where(Call.order_id == order.id, Call.kind.in_(("supplier_r1", "supplier_r2")))
                                 .order_by(Call.round, Call.id)))
    by_sup: dict[str, list[Call]] = {}
    for c in calls:
        if c.supplier_key and c.round in rounds and c.supplier_key not in exclude:
            by_sup.setdefault(c.supplier_key, []).append(c)
    inputs, flagged = [], []
    for key, clist in by_sup.items():
        sup = sups.get(key)
        if sup is None:
            continue
        items: dict[str, ranking.ItemQuote] = {}
        delivery, credit, fee = None, 0.0, 0.0
        for c in clist:
            times, credits, fees = [], [], []
            for q in session.scalars(select(Quote).where(Quote.call_id == c.id)):
                if q.flagged:
                    flagged.append({"supplier": key, "item": q.item, "reason": q.flag_reason, "raw": q.raw_text})
                    continue
                if q.available is False:
                    items.setdefault(q.item, ranking.ItemQuote(0.0, q.base_unit or "kg", False, q.provisional))
                    continue
                if not _usable(q):
                    continue
                new = ranking.ItemQuote(q.price_per_base, q.base_unit, True, q.provisional)  # type: ignore[arg-type]
                old = items.get(q.item)
                if old is None or not old.available or new.price_per_base <= old.price_per_base:
                    items[q.item] = new
                if q.delivery_time:
                    times.append(q.delivery_time)
                if q.credit_days is not None:
                    credits.append(q.credit_days)
                if q.delivery_fee is not None:
                    fees.append(q.delivery_fee)
            if times:
                delivery = max(times, key=lambda t: ranking.parse_clock(t) if ranking.parse_clock(t) is not None else 10**6)
            if credits:
                credit = float(max(credits))
            if fees:
                fee = float(max(fees))
        if items:
            inputs.append(ranking.SupplierInput(key, sup.name, items, delivery, credit, fee, sup.on_time_count, sup.late_count))
    return inputs, flagged


def confirmed_prices(session: Session, order: Order) -> dict[str, dict[str, tuple[float, str]]]:
    """Only prices confirmed at `completed` in round 1 may be quoted to another supplier."""
    out: dict[str, dict[str, tuple[float, str]]] = {}
    for c in session.scalars(select(Call).where(Call.order_id == order.id, Call.kind == "supplier_r1", Call.status == "completed")):
        for q in session.scalars(select(Quote).where(Quote.call_id == c.id, Quote.provisional.is_(False))):
            if _usable(q) and q.available is not False and c.supplier_key:
                out.setdefault(c.supplier_key, {})[q.item] = (q.price_per_base, q.base_unit)  # type: ignore[assignment]
    return out


# ================================================================== ranking snapshot
def _rank(session: Session, order: Order, rounds: tuple[int, ...], s: Settings, exclude: frozenset[str] = frozenset()) -> dict:
    cfg = ranking.RankConfig.from_settings(s)
    lines = ranking.order_lines(order.items)
    inputs, flagged = supplier_inputs(session, order, rounds, exclude)
    res = ranking.rank_suppliers(lines, order.deadline, inputs, cfg)
    dec = ranking.decide(lines, order.deadline, inputs, cfg)
    note = ranking.ranked_lower_note(res.ranked)
    return {
        "rounds": list(rounds),
        "ranked": [r.breakdown() for r in res.ranked],
        "infeasible": [{"key": i.key, "name": i.name, "reasons": i.reasons, "covers": i.covers} for i in res.infeasible],
        "decision": dec.as_dict(), "ranked_lower": note, "flagged": flagged,
        "suppliers_heard": len(inputs),
    }


def _usual_supplier_total(session: Session, order: Order, snap: dict) -> float | None:
    usual = [x.key for x in _suppliers_by_key(session, order).values() if x.is_usual]
    for r in snap["ranked"]:
        if r["key"] in usual:
            return r["quoted_total"]
    return None


# ============================================================================== dialer
def _wave(call: Call) -> int:
    return int((call.user_data or {}).get("wave") or 0)


def _wave_blocked(session: Session, call: Call, order: Order | None, s: Settings, now: datetime) -> bool:
    """A round-1 wave waits until every earlier wave has finished, or until its own time slot opens
    (so one stuck call cannot hold up the rest of the suppliers)."""
    if call.kind != "supplier_r1" or order is None or _wave(call) == 0:
        return False
    opens = (aware(order.r1_started_at) or now) + timedelta(seconds=_wave(call) * s.round1_deadline_seconds)
    if now >= opens:
        return False
    return not _all_done([c for c in _calls(session, order.id, "supplier_r1") if _wave(c) < _wave(call)])


def _anchor_call(session: Session, call: Call, order: Order) -> None:
    """Right before a later-wave call is dialed, give it the best confirmed rival prices for the items
    this supplier sells, so the agent can bargain live. Real prices only, re-checked here."""
    confirmed = confirmed_prices(session, order)
    data = dict(call.user_data or {})
    anchors = negotiation.build_anchors(call.supplier_key or "", data.get("sells") or [], confirmed)
    try:
        negotiation.assert_real_anchors(call.supplier_key or "", anchors, confirmed)
    except negotiation.FabricatedPriceError as e:
        log.error("blocked a fabricated anchor: %s", e)
        anchors = []
    data["competing_quote_spoken"] = negotiation.spoken_anchors(anchors) or "none"
    data["anchors"] = [{"item": a.item, "price": a.price, "unit": a.base_unit} for a in anchors]
    session.execute(update(Call).where(Call.id == call.id).values(user_data=data))
    session.commit()
    session.refresh(call)
    if anchors:
        orders.emit(session, order.id, "anchor", {"supplier": call.supplier_key, "wave": _wave(call),
                                                  "anchors": data["anchors"], "from": sorted({a.from_supplier for a in anchors})})


def _cancel_call(session: Session, call_id: int, why: str) -> None:
    session.execute(update(Call).where(Call.id == call_id, Call.status_rank < statuses.TERMINAL_RANK)
                    .values(status="canceled", status_rank=statuses.TERMINAL_RANK))
    session.commit()
    orders.emit(session, None, "call_canceled", {"call_id": call_id, "why": why})


def dispatch_pending(session: Session, provider: providers_mod.Provider, s: Settings, now: datetime | None = None) -> int:
    """Hand pending calls to the provider while guards and concurrency allow. Returns calls placed."""
    now = now or now_utc()
    placed = 0
    for call in list(session.scalars(select(Call).where(Call.status_rank == -1).order_by(Call.id))):
        order = session.get(Order, call.order_id) if call.order_id else None
        if order is not None and order.state in orders.TERMINAL_STATES:
            _cancel_call(session, call.id, "order finished")
            continue
        if _wave_blocked(session, call, order, s, now):
            continue
        try:
            guards.check_can_dial(session, call.order_id, s, now)
        except guards.GuardRefused as e:
            if "concurrency" in str(e):
                break  # a slot frees when a call finishes; the next tick continues
            _cancel_call(session, call.id, str(e))
            orders.emit(session, call.order_id, "guard", {"call_id": call.id, "reason": str(e)})
            continue
        if order is not None and call.kind == "supplier_r1" and _wave(call) > 0:
            _anchor_call(session, call, order)
        try:
            exec_id = provider.place_call(call.kind or "", call.to_number or "", call.user_data or {})
        except Exception as e:  # noqa: BLE001  (DialRefused, BolnaError, missing agent id ...)
            session.execute(update(Call).where(Call.id == call.id).values(status="failed", status_rank=statuses.TERMINAL_RANK))
            session.commit()
            orders.emit(session, call.order_id, "dial_error", {"call_id": call.id, "kind": call.kind, "error": str(e)})
            log.warning("could not place call %s: %s", call.id, e)
            continue
        session.execute(update(Call).where(Call.id == call.id, Call.status_rank == -1)
                        .values(execution_id=exec_id, status="queued", status_rank=1, placed_at=now))
        session.commit()
        orders.emit(session, call.order_id, "call_placed", {"call_id": call.id, "kind": call.kind, "supplier": call.supplier_key,
                                                           "execution_id": exec_id})
        placed += 1
    return placed


def watchdog(session: Session, provider: providers_mod.Provider, s: Settings, now: datetime | None = None) -> int:
    """Poll calls that went quiet (a lost webhook must not hang an order). Returns calls updated."""
    now = now or now_utc()
    cutoff = now - timedelta(seconds=s.poll_stale_after_seconds)
    updated = 0
    for call in list(session.scalars(select(Call).where(Call.status_rank.between(1, 5), Call.execution_id.is_not(None)))):
        placed = aware(call.placed_at)
        last = aware(call.updated_at) or placed
        if placed is None or (last and last > cutoff):
            continue
        try:
            payload = provider.fetch_execution(call.execution_id)  # type: ignore[arg-type]
        except Exception as e:  # noqa: BLE001
            log.warning("poll failed for %s: %s", call.execution_id, e)
            continue
        if payload and statuses.rank(payload.get("status")) is not None:
            orders.emit(session, call.order_id, "polled", {"call_id": call.id, "status": payload.get("status")})
            process_webhook(session, payload, run_tick=False)
            updated += 1
    return updated


# ============================================================== webhook entry points
def process_webhook(session: Session, payload: dict, run_tick: bool = True) -> dict:
    """Apply one status payload (real webhook, fake delivery, or poll result), then react to it."""
    with LOCK:
        res = services.apply_webhook(session, payload)
        call = services.find_call(session, call_ref=(payload.get("context_details") or {}).get("call_ref"),
                                  execution_id=payload.get("id") or payload.get("execution_id"))
        if call is None:
            return res
        session.refresh(call)
        if res.get("advanced") and call.order_id:
            orders.emit(session, call.order_id, "call", {"call_id": call.id, "kind": call.kind, "supplier": call.supplier_key,
                                                         "status": call.status})
        if res.get("advanced") and statuses.is_terminal(call.status):
            _on_terminal(session, call)
        session.refresh(call)
        if run_tick and call.order_id:
            tick(session, order_id=call.order_id)
        return res


def process_tool_quote(session: Session, data: dict) -> Quote | None:
    q = services.record_tool_quote(session, data)
    if q is not None:
        call = services.find_call(session, data.get("call_ref"), data.get("execution_id"))
        if call is not None and call.order_id:
            orders.emit(session, call.order_id, "quote", {"supplier": call.supplier_key, "item": q.item, "price": q.unit_price,
                                                          "unit": q.unit, "provisional": q.provisional, "flagged": q.flagged,
                                                          "round": call.round})
    return q


def _on_terminal(session: Session, call: Call) -> None:
    sup = None
    if call.supplier_key and call.order_id:
        order = session.get(Order, call.order_id)
        if order:
            sup = _suppliers_by_key(session, order).get(call.supplier_key)
    if call.status in ("no-answer", "busy", "failed") and sup is not None:
        sup.no_answer_count = (sup.no_answer_count or 0) + 1
        session.commit()
        _maybe_retry(session, call)
    if call.status != "completed":
        return
    if call.answered_by_voicemail:
        orders.emit(session, call.order_id, "voicemail", {"call_id": call.id, "supplier": call.supplier_key})
        _maybe_retry(session, call)
    if sup is not None and services.yes_no(services.extraction_value(call.extracted_data, "do_not_call")) is True:
        sup.do_not_call = True
        session.commit()
        orders.emit(session, call.order_id, "do_not_call", {"supplier": sup.key})
    if call.kind in (None, "intake") and services.extraction_value(call.extracted_data, "order_json") is not None:
        _handle_intake(session, call)


def _maybe_retry(session: Session, call: Call) -> None:
    """One more try for a round-1 supplier who did not pick up (ticket #22), if there is still time."""
    s = get_settings()
    if not s.retry_no_answer or call.kind != "supplier_r1" or (call.user_data or {}).get("retry"):
        return
    order = session.get(Order, call.order_id) if call.order_id else None
    if order is None or order.state != orders.COLLECTING_R1:
        return
    left = (aware(order.r1_deadline_at) or now_utc()) - now_utc()
    if left < timedelta(seconds=s.retry_min_seconds_left):
        return
    data = {k: v for k, v in (call.user_data or {}).items() if k not in ("call_ref", "kind", "supplier_key")}
    plan_call(session, order, "supplier_r1", call.to_number or "", {**data, "retry": 1}, supplier_key=call.supplier_key, round_=1)
    orders.emit(session, order.id, "retry", {"supplier": call.supplier_key, "after": call.status})


def plan_intake_call(session: Session, owner_id: int) -> Call:
    """Outbound intake: the intake agent rings the owner so a new order can be taken by voice without
    needing an inbound number (an inbound call is read by the same code once its webhook arrives)."""
    s = get_settings()
    owner = session.get(Owner, owner_id)
    phone = (_owner_phone(owner, s) if owner else None)
    if not phone:
        raise OrderInvalid("the owner has no phone number")
    ref = _new_ref(0, "intake", "owner")
    call = Call(call_ref=ref, order_id=None, kind="intake", to_number=phone, status="pending", status_rank=-1,
                user_data={"call_ref": ref, "kind": "intake", "owner_id": owner_id, "owner_name": owner.name, "supplier_key": "",
                           "agent_language": bolna_setup.call_language(owner.language)})
    session.add(call)
    session.commit()
    return call


def _handle_intake(session: Session, call: Call) -> None:
    data = services.extraction_value(call.extracted_data, "order_json")
    s = get_settings()
    try:
        if not isinstance(data, dict):
            raise OrderInvalid("order_json is not an object")
        owner_id = (call.user_data or {}).get("owner_id")
        if not owner_id:
            first = session.scalar(select(Owner).order_by(Owner.id))
            if first is None:
                raise OrderInvalid("no owner to attach the order to")
            owner_id = first.id
        order = create_order(session, int(owner_id), data.get("items") or [], data.get("deadline"), data.get("budget"), s)
    except (OrderInvalid, ValueError, TypeError) as e:
        orders.emit(session, None, "intake_rejected", {"call_id": call.id, "error": str(e), "order_json": data})
        return
    session.execute(update(Call).where(Call.id == call.id).values(order_id=order.id, kind="intake"))
    session.commit()
    orders.emit(session, order.id, "intake", {"call_id": call.id})
    start_order(session, order.id, s)


# ================================================================ state handlers
def _calls(session: Session, order_id: int, *kinds: str) -> list[Call]:
    return list(session.scalars(select(Call).where(Call.order_id == order_id, Call.kind.in_(kinds)).order_by(Call.id)))


def _all_done(calls: list[Call]) -> bool:
    return all(c.status_rank >= statuses.TERMINAL_RANK for c in calls)


def _cancel_pending(session: Session, order_id: int, why: str) -> None:
    for c in session.scalars(select(Call).where(Call.order_id == order_id, Call.status_rank == -1)):
        _cancel_call(session, c.id, why)


def _fail(session: Session, order_id: int, reason: str) -> bool:
    ok = orders.fail(session, order_id, reason)
    if ok:
        _cancel_pending(session, order_id, f"order failed: {reason}")
        _finalize_cost(session, order_id)
        notifier.send(session, order_id, f"Order could not be completed: {reason.replace('_', ' ')}. Nothing was booked.", "failure")
    return ok


def _finalize_cost(session: Session, order_id: int) -> None:
    o = session.get(Order, order_id)
    if o:
        o.cost_incurred = round(guards.order_spend_inr(session, order_id, get_settings()), 2)
        session.commit()


def _h_collecting(session: Session, order: Order, s: Settings, now: datetime) -> bool:
    calls = _calls(session, order.id, "supplier_r1")
    hit = now >= (aware(order.r1_deadline_at) or now)
    if not (_all_done(calls) or hit):
        return False
    if hit:
        _cancel_pending(session, order.id, "round-1 deadline")
    snap = _rank(session, order, (1,), s)
    snap["r2_done"] = False
    snap["deadline_hit"] = bool(hit and not _all_done(calls))
    if snap["decision"]["kind"] == "none":
        reason = "no_quotes" if snap["suppliers_heard"] == 0 else "no_supplier_can_deliver_in_time"
        return _fail(session, order.id, reason)
    fields: dict[str, Any] = {"ranking": snap, "assignments": snap["decision"]["assignments"]}
    if order.baseline_total is None:
        usual = _usual_supplier_total(session, order, snap)
        if usual:
            fields.update(baseline_total=usual, baseline_kind="usual_supplier_quote")
    return orders.transition(session, order.id, orders.RANKED, **fields)


def _h_ranked(session: Session, order: Order, s: Settings, now: datetime) -> bool:
    snap = dict(order.ranking or {})
    if not snap.get("r2_done"):
        targets = [r["key"] for r in snap.get("ranked", [])[:2]]
        confirmed = confirmed_prices(session, order)
        offers = {k: v for k, v in negotiation.build_counter_offers(targets, confirmed).items() if v}
        snap["r2_done"] = True
        if offers:
            negotiation.assert_real_offers(offers, confirmed)
            snap["round2_targets"] = sorted(offers)
            if not orders.transition(session, order.id, orders.NEGOTIATING_R2, ranking=snap):
                return False
            sups = _suppliers_by_key(session, order)
            for key, offs in offers.items():
                plan_call(session, order, "supplier_r2", sups[key].phone or "", {
                    "business_name": _owner(session, order).business_name, "items_spoken": speak_items(order.items),
                    "deadline_spoken": speak_clock(order.deadline), "items_list": order.items, "supplier_name": sups[key].name,
                    "counter": [{"item": o.item, "price": o.competing_price} for o in offs],
                    "counter_offer_spoken": negotiation.spoken_counter(offs),
                    "their_quote_spoken": negotiation.spoken_their_quote(offs),
                }, supplier_key=key, round_=2)
            return True
        order.ranking = snap
        session.commit()
    return _after_ranking(session, order, s, now)


def _h_negotiating(session: Session, order: Order, s: Settings, now: datetime) -> bool:
    calls = _calls(session, order.id, "supplier_r2")
    timed_out = now - (aware(order.stage_started_at) or now) > timedelta(seconds=s.stage_timeout_seconds)
    if not (_all_done(calls) or timed_out):
        return False
    if timed_out:
        _cancel_pending(session, order.id, "round-2 timeout")
    before = {r["key"]: r["quoted_total"] for r in (order.ranking or {}).get("ranked", [])}
    snap = _rank(session, order, (1, 2), s)
    old = order.ranking or {}
    snap["r2_done"] = True
    snap["round2_targets"] = old.get("round2_targets", [])
    snap["round1"] = {"ranked": old.get("ranked"), "decision": old.get("decision")}
    snap["round2_changes"] = [{"key": r["key"], "from": before[r["key"]], "to": r["quoted_total"], "credit_days": r["credit_days"]}
                              for r in snap["ranked"] if r["key"] in before and (r["quoted_total"] < before[r["key"]] or r["credit_days"])]
    if snap["decision"]["kind"] == "none":  # round 2 cannot make things worse than round 1; keep round 1
        snap = {**old, "round2_changes": []}
    return orders.transition(session, order.id, orders.RERANKED, ranking=snap, assignments=snap["decision"]["assignments"])


def approval_reasons(order: Order, dec: dict, snap: dict) -> list[str]:
    reasons = []
    cash = ranking.cash_total(dec.get("per_supplier") or [])
    if dec["kind"] == "partial":
        reasons.append(f"partial order: cannot get {', '.join(dec.get('uncovered', []))}")
    if order.budget is not None and cash > order.budget:
        reasons.append(f"over budget: {inr(cash)} vs {inr(order.budget)}")
    chosen = set(dec.get("suppliers", []))
    if any(r["unconfirmed"] for r in snap.get("ranked", []) if r["key"] in chosen):
        reasons.append("price heard only during the call, not yet confirmed")
    return reasons


def _after_ranking(session: Session, order: Order, s: Settings, now: datetime) -> bool:
    session.refresh(order)
    snap = order.ranking or {}
    dec = snap["decision"]
    reasons = approval_reasons(order, dec, snap)
    cash = ranking.cash_total(dec.get("per_supplier") or [])
    if reasons:
        approval = {"status": "pending", "reasons": reasons, "cash_total": cash}
        if not orders.transition(session, order.id, orders.AWAITING_APPROVAL, approval=approval, assignments=dec["assignments"]):
            return False
        owner = _owner(session, order)
        phone = _owner_phone(owner, s)
        summary = (f"{owner.name} ji, {speak_items(order.items)} ka best option {', '.join(dec['suppliers'])} se {inr(cash)}. "
                   f"{'; '.join(reasons)}. Book kar dun?")
        if phone:
            plan_call(session, order, "approval", phone, {"owner_name": owner.name, "summary": summary, "total": cash,
                                                          "reasons": "; ".join(reasons)})
        return True
    if not orders.transition(session, order.id, orders.BOOKING, assignments=dec["assignments"], booking_attempts=0):
        return False
    _plan_confirms(session, order, s)
    return True


def _h_approval(session: Session, order: Order, s: Settings, now: datetime) -> bool:
    calls = _calls(session, order.id, "approval")
    timed_out = now - (aware(order.stage_started_at) or now) > timedelta(seconds=s.stage_timeout_seconds)
    call = calls[-1] if calls else None
    if call is None or not _all_done([call]):
        if call is None or timed_out:
            if call is not None:
                _cancel_pending(session, order.id, "approval timeout")
            return _fail(session, order.id, "approval_unanswered")
        return False
    val = services.extraction_value(call.extracted_data, "approval")
    said = services.yes_no(val)  # only a clear yes books; "unclear" or nothing is not a yes
    decision = str(val.get("decision") if isinstance(val, dict) else (val or "")).strip()[:200]
    approval = {**(order.approval or {}), "status": {True: "approved", False: "declined"}.get(said, "unanswered"),  # type: ignore[arg-type]
                "decision": decision}
    order.approval = approval
    session.commit()
    if said is True:
        if not orders.transition(session, order.id, orders.BOOKING, approval=approval, booking_attempts=0):
            return False
        _plan_confirms(session, order, s)
        return True
    return _fail(session, order.id, "owner_declined" if said is False else "approval_unanswered")


# -- booking ---------------------------------------------------------------------------------
def _supplier_items(assign: dict[str, str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for item, key in assign.items():
        out.setdefault(key, []).append(item)
    return {k: sorted(v) for k, v in out.items()}


def _parts_for(session: Session, order: Order, assign: dict[str, str], s: Settings) -> list[dict]:
    cfg = ranking.RankConfig.from_settings(s)
    inputs, _ = supplier_inputs(session, order, (1, 2))
    sups = {i.key: i for i in inputs}
    lines = {ln.name: ln for ln in ranking.order_lines(order.items)}
    _, _, parts = ranking.assignment_cost(lines, assign, sups, cfg)
    return parts


def _plan_confirms(session: Session, order: Order, s: Settings) -> None:
    assign = order.assignments or {}
    parts = {p["key"]: p for p in _parts_for(session, order, assign, s)}
    sups = _suppliers_by_key(session, order)
    inputs, _ = supplier_inputs(session, order, (1, 2))
    delivery = {i.key: i.delivery_time for i in inputs}
    lines = {ln.name: ln for ln in ranking.order_lines(order.items)}
    existing = {(c.supplier_key, tuple(sorted((c.user_data or {}).get("items", [])))) for c in _calls(session, order.id, "confirm")}
    for key, items in _supplier_items(assign).items():
        if (key, tuple(items)) in existing:
            continue
        part = parts[key]
        agreed = []
        for it in items:
            ln = lines[it]
            q = next(i for i in inputs if i.key == key).quotes[it]
            agreed.append({"item": it, "quantity": ln.quantity, "unit": ln.unit, "price": q.price_per_base})
        plan_call(session, order, "confirm", sups[key].phone or "", {
            "business_name": _owner(session, order).business_name, "items": items, "agreed": agreed,
            "agreed_spoken": ", ".join(f"{negotiation.number_text(a['quantity'])} {_unit_word(a['unit'])} {a['item']} "
                                       f"{negotiation.number_text(a['price'])} rupaye {_unit_word(a['unit'])}" for a in agreed),
            "expected_total": part["subtotal"] + (part.get("delivery_fee") or 0),
            "delivery_time": delivery.get(key), "deadline_spoken": speak_clock(order.deadline),
            "attempt": order.booking_attempts}, supplier_key=key, round_=3)


def confirm_result(call: Call, order: Order, items: list[str], s: Settings) -> tuple[bool, str]:
    """(ok, reason). A confirmation counts only if it matches what we asked for.

    Hanging up is NOT a failure by itself: Bolna still marks the call `completed` and extracts from the
    transcript, so a supplier who said yes and then hung up is confirmed. What fails a booking: the call
    never connected (no-answer, busy, failed), no clear yes, the supplier changed a quantity, price or time,
    or the total they agreed differs from ours. Two answer shapes are read:
      * separate extractions `confirmed` (yes/no), `confirm_changed` (yes/no), `confirm_total` (number),
        `confirm_delivery_time` (text): what bolna/extractions.json creates, robust to prose answers;
      * one JSON object in `confirmed` ({"confirmed", "quantities", "total", ...}): the older shape.
    """
    if call.status != "completed":
        return False, f"call {call.status}"
    val = services.extraction_value(call.extracted_data, "confirmed")
    if not isinstance(val, dict):
        said = services.yes_no(val)
        if said is not True:
            return False, "supplier said no" if said is False else "no clear yes from the supplier"
        if services.yes_no(services.extraction_value(call.extracted_data, "confirm_changed")) is True:
            return False, "supplier changed a quantity, price or delivery time"
        val = {"confirmed": True, "total": services.number(services.extraction_value(call.extracted_data, "confirm_total")) or None}
    if services.yes_no(val.get("confirmed")) is not True:
        return False, (val.get("reason") if val.get("reason") else "not confirmed")
    ordered = {i["name"]: i["quantity"] for i in order.items}
    for item, qty in (val.get("quantities") or {}).items():
        if item in items:
            try:
                q = float(qty)
            except (TypeError, ValueError):
                return False, f"quantity for {item} unreadable"
            if abs(q - ordered[item]) > 1e-6 or q > s.max_quantity_per_item:
                return False, f"quantity mismatch for {item}: said {q:g}, ordered {ordered[item]:g}"
    expected = (call.user_data or {}).get("expected_total")
    total = val.get("total")
    if expected and total not in (None, ""):
        try:
            if abs(float(total) - float(expected)) > max(5.0, 0.05 * float(expected)):
                return False, f"total mismatch: said {float(total):g}, expected {float(expected):g}"
        except (TypeError, ValueError):
            return False, "total unreadable"
    return True, "ok"


def _h_booking(session: Session, order: Order, s: Settings, now: datetime) -> bool:
    assign = order.assignments or {}
    groups = _supplier_items(assign)
    calls = _calls(session, order.id, "confirm")
    timed_out = now - (aware(order.stage_started_at) or now) > timedelta(seconds=s.stage_timeout_seconds)
    status: dict[str, str] = {}
    reasons: dict[str, str] = {}
    for key, items in groups.items():
        mine = [c for c in calls if c.supplier_key == key and tuple(sorted((c.user_data or {}).get("items", []))) == tuple(items)]
        if not mine:
            status[key] = "missing"
            continue
        c = mine[-1]
        if not _all_done([c]):
            status[key] = "failed" if timed_out else "pending"
            reasons[key] = "timeout"
            continue
        ok, why = confirm_result(c, order, items, s)
        status[key], reasons[key] = ("confirmed" if ok else "failed"), why
    if "missing" in status.values():
        _plan_confirms(session, order, s)
        return False
    if "pending" in status.values():
        return False
    failed = [k for k, v in status.items() if v == "failed"]
    if not failed:
        return _book(session, order, s)
    for k in failed:
        orders.emit(session, order.id, "confirm_failed", {"supplier": k, "reason": reasons.get(k)})
    return _rebook(session, order, s, failed, {k for k, v in status.items() if v == "confirmed"})


def _rebook(session: Session, order: Order, s: Settings, failed: list[str], confirmed_keys: set[str]) -> bool:
    attempts = order.booking_attempts + 1
    if attempts >= s.max_booking_attempts:
        return _fail(session, order.id, "booking_failed")
    excluded = sorted(set(order.excluded_suppliers or []) | set(failed))
    locked = {i: k for i, k in (order.assignments or {}).items() if k in confirmed_keys}
    remaining = [i for i in order.items if i["name"] not in locked]
    cfg = ranking.RankConfig.from_settings(s)
    inputs, _ = supplier_inputs(session, order, (1, 2), frozenset(excluded))
    dec = ranking.decide(ranking.order_lines(remaining), order.deadline, inputs, cfg)
    if dec.kind not in ("single", "split") or dec.uncovered:
        return _fail(session, order.id, "booking_failed")
    new_assign = {**locked, **dec.assignments}
    parts = _parts_for(session, order, new_assign, s)
    cash = ranking.cash_total(parts)
    if order.budget is not None and cash > order.budget and not (order.approval or {}).get("status") == "approved":
        return _fail(session, order.id, "runner_up_over_budget")
    snap = dict(order.ranking or {})
    snap["decision"] = {**snap.get("decision", {}), "assignments": new_assign, "suppliers": sorted(set(new_assign.values())),
                        "per_supplier": parts, "quoted_total": cash, "note": f"re-planned after {', '.join(failed)} could not confirm"}
    res = session.execute(update(Order).where(Order.id == order.id, Order.state == orders.BOOKING)
                          .values(assignments=new_assign, excluded_suppliers=excluded, booking_attempts=attempts, ranking=snap,
                                  stage_started_at=now_utc()))
    session.commit()
    if res.rowcount != 1:
        return False
    orders.emit(session, order.id, "rebook", {"failed": failed, "new_assignments": new_assign, "attempt": attempts})
    session.refresh(order)
    _plan_confirms(session, order, s)
    return True


def _book(session: Session, order: Order, s: Settings) -> bool:
    parts = _parts_for(session, order, order.assignments or {}, s)
    total = ranking.cash_total(parts)
    sv = savings.savings(order.baseline_total, total)
    owner = _owner(session, order)
    secs = sum(c.duration or 0 for c in _calls(session, order.id, *OWNER_KINDS))
    ts = savings.time_saved_minutes(owner.manual_minutes_per_order, secs)
    snap = dict(order.ranking or {})
    snap["decision"] = {**snap.get("decision", {}), "per_supplier": parts, "quoted_total": total}
    ok = orders.transition(session, order.id, orders.BOOKED, booked_total=total, savings=sv["savings"], time_saved_min=ts, ranking=snap)
    if ok:
        session.refresh(order)
        _plan_callback(session, order, s, parts, total, sv["savings"])
    return ok


def _plan_callback(session: Session, order: Order, s: Settings, parts: list[dict], total: float, saved: float | None) -> None:
    owner = _owner(session, order)
    who = ", ".join(f"{p['name']} ({', '.join(p['items'])})" for p in parts)
    msg = f"{owner.name} ji, order book ho gaya: {who}. Total {inr(total)}"
    if saved:
        base = "pichli baar ke daam" if order.baseline_kind == "owner_last_paid_price" else "aapke usual supplier ke aaj ke daam"
        msg += f", {base} se {inr(saved)} ki bachat"
    msg += f". Delivery {speak_clock(order.deadline)} tak."
    notifier.send(session, order.id, msg, "booked")
    phone = _owner_phone(owner, s)
    if phone:
        plan_call(session, order, "callback", phone, {"owner_name": owner.name, "message": msg, "savings": saved or 0, "total": total})


def _h_booked(session: Session, order: Order, s: Settings, now: datetime) -> bool:
    calls = _calls(session, order.id, "callback")
    timed_out = now - (aware(order.stage_started_at) or now) > timedelta(seconds=s.stage_timeout_seconds)
    if calls and not _all_done(calls) and not timed_out:
        return False
    secs = sum(c.duration or 0 for c in _calls(session, order.id, *OWNER_KINDS))
    ts = savings.time_saved_minutes(_owner(session, order).manual_minutes_per_order, secs)
    if calls and not any(c.status == "completed" for c in calls):
        orders.emit(session, order.id, "callback_unanswered", {"note": "owner was sent the summary instead"})
    ok = orders.transition(session, order.id, orders.REPORTED, time_saved_min=ts)
    if ok:
        _finalize_cost(session, order.id)
    return ok


_HANDLERS = {
    orders.COLLECTING_R1: _h_collecting, orders.RANKED: _h_ranked, orders.NEGOTIATING_R2: _h_negotiating,
    orders.RERANKED: _after_ranking, orders.AWAITING_APPROVAL: _h_approval, orders.BOOKING: _h_booking,
    orders.BOOKED: _h_booked,
}


# ================================================================================ tick
def tick(session: Session, provider: providers_mod.Provider | None = None, settings: Settings | None = None,
         now: datetime | None = None, order_id: int | None = None) -> dict:
    """Advance everything as far as the data allows. Safe to call from anywhere, any number of times."""
    s = settings or get_settings()
    provider = provider or providers_mod.get_provider()
    now = now or now_utc()
    changed = 0
    with LOCK:
        session.expire_all()
        q = select(Order.id).where(Order.state.notin_([orders.DRAFT, *orders.TERMINAL_STATES]))
        if order_id is not None:
            q = q.where(Order.id == order_id)
        for oid in list(session.scalars(q)):
            for _ in range(12):  # chain through states while data allows
                order = orders.get_order(session, oid)
                handler = _HANDLERS.get(order.state) if order else None
                if handler is None:
                    break
                try:
                    moved = handler(session, order, s, now)
                except negotiation.FabricatedPriceError as e:
                    log.error("blocked a fabricated counter-offer: %s", e)
                    _fail(session, oid, "fabricated_price_blocked")
                    moved = True
                except Exception as e:  # noqa: BLE001
                    session.rollback()
                    log.exception("order %s handler failed", oid)
                    orders.emit(session, oid, "error", {"state": order.state, "error": str(e)})
                    break
                if not moved:
                    break
                changed += 1
        polled = watchdog(session, provider, s, now)
        placed = dispatch_pending(session, provider, s, now)
    return {"changed": changed, "polled": polled, "placed": placed}


def run_until_idle(session: Session, provider: providers_mod.Provider | None = None, settings: Settings | None = None,
                   max_rounds: int = 80, now_fn=None) -> int:
    """Test/demo driver: tick, deliver every queued fake event, repeat until nothing moves."""
    provider = provider or providers_mod.get_provider()
    rounds = 0
    quiet = 0
    while rounds < max_rounds and quiet < 2:
        rounds += 1
        r = tick(session, provider, settings, now=now_fn() if now_fn else None)
        n = provider.pump(session, force=True)
        quiet = quiet + 1 if (n == 0 and r["changed"] == 0 and r["placed"] == 0 and r["polled"] == 0) else 0
    return rounds
