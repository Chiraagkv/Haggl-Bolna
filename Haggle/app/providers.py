"""Where calls go: real Bolna, or a scripted fake (tickets #20 and #23).

The orchestrator only knows the Provider interface:

    place_call(kind, to_number, user_data) -> execution_id
    fetch_execution(execution_id)          -> dict like GET /executions/{id}, or None
    pump(session, force=False)             -> deliver due fake events (real provider: no-op)
    wallet_inr()                           -> money left on the account in rupees, or None if unknown

PROVIDER=fake runs the whole product with no key, no phone and no cost: suppliers are played from
data/personas.json and answer through the same webhook and tool code paths as real Bolna would.
That is how every flow, failure and edge case is tested, and how the dashboard demo runs offline.
"""

from __future__ import annotations

import itertools
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Protocol

import httpx

from app import safety
from app.bolna_client import BolnaClient, BolnaError
from app.config import Settings, get_settings
from app.seed import load_personas

log = logging.getLogger("dalaal.providers")

class Provider(Protocol):
    name: str

    def place_call(self, kind: str, to_number: str, user_data: dict) -> str: ...
    def fetch_execution(self, execution_id: str) -> dict | None: ...
    def pump(self, session: Any, force: bool = False) -> int: ...
    def wallet_inr(self) -> float | None: ...


# ------------------------------------------------------------------------------- Bolna
class BolnaProvider:
    name = "bolna"

    def __init__(self, settings: Settings | None = None, client: BolnaClient | None = None):
        self.s = settings or get_settings()
        self._client = client

    @property
    def client(self) -> BolnaClient:
        if self._client is None:
            self._client = BolnaClient()
        return self._client

    def agent_for(self, kind: str) -> str:
        s = self.s
        agent = {
            "supplier_r1": s.supplier_agent_id,
            "supplier_r2": s.supplier_r2_agent_id or s.supplier_agent_id,
            "approval": s.approval_agent_id,
            "confirm": s.confirm_agent_id,
            "callback": s.callback_agent_id,
            "intake": s.intake_agent_id,
        }.get(kind, "")
        if not agent:
            raise BolnaError(f"no agent id configured for call kind {kind!r} (see .env.example)")
        return agent

    def place_call(self, kind: str, to_number: str, user_data: dict) -> str:
        safety.check_can_dial(to_number, self.s)
        flat = {k: (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)) for k, v in user_data.items()}
        return self.client.make_call(self.agent_for(kind), to_number, user_data=flat)["execution_id"]

    def fetch_execution(self, execution_id: str) -> dict | None:
        return self.client.get_execution(execution_id)

    def pump(self, session: Any, force: bool = False) -> int:
        return 0

    def wallet_inr(self) -> float | None:
        """GET /user/me wallet (US cents), converted with WALLET_UNIT_TO_INR. None if it cannot be read: the
        order then goes ahead and Bolna itself ends calls with `balance-low` when money runs out."""
        try:
            wallet = self.client.account().get("wallet")
            return float(wallet) * self.s.wallet_unit_to_inr if wallet is not None else None
        except (BolnaError, httpx.HTTPError, TypeError, ValueError) as e:
            log.warning("could not read the Bolna wallet: %s", e)
            return None


# -------------------------------------------------------------------------------- fake
@dataclass
class _Item:
    due: float
    seq: int
    exec_id: str
    type: str            # webhook | tool
    data: dict


@dataclass
class FakeCall:
    exec_id: str
    kind: str
    to_number: str
    user_data: dict
    final: dict | None = None      # the `completed` payload (what fetch_execution returns)


class FakeProvider:
    """Plays suppliers and the owner. Deterministic; behaviours can be injected per supplier.

    behaviours (set `fake.behaviour["kumar"] = "no-answer"`):
      normal | no-answer | busy | voicemail | hang (never finishes) | lost_webhook (finishes, webhook
      never arrives; only polling finds it) | out_of_stock | late | bad_unit | refuses_confirm |
      wrong_quantity | do_not_call
    owner: `fake.owner = "yes" | "no" | "no-answer"`.
    """

    name = "fake"

    def __init__(self, delay: float = 0.0, sink: Callable | None = None, tool_sink: Callable | None = None,
                 personas: dict | None = None):
        self.delay = delay
        self.personas = personas or load_personas()
        self.suppliers = {s["key"]: s for s in self.personas["suppliers"]}
        self.behaviour: dict[str, str] = {}
        self.owner = "yes"
        self.use_split_variant = False
        self.intake_order: dict | None = None
        self.calls: dict[str, FakeCall] = {}
        self.placed: list[FakeCall] = []
        self._outbox: list[_Item] = []
        self._ids = itertools.count(1)
        # Per-run token: the database outlives the server, so ids from an earlier run must never repeat.
        self._run = uuid.uuid4().hex[:6]
        self._seq = itertools.count(1)
        self._lock = threading.Lock()
        self._sink = sink
        self._tool_sink = tool_sink

    # -- Provider API -------------------------------------------------------
    def place_call(self, kind: str, to_number: str, user_data: dict) -> str:
        exec_id = f"fake-exec-{self._run}-{next(self._ids)}"
        call = FakeCall(exec_id, kind, to_number, dict(user_data))
        with self._lock:
            self.calls[exec_id] = call
            self.placed.append(call)
        self._script(call)
        return exec_id

    def fetch_execution(self, execution_id: str) -> dict | None:
        c = self.calls.get(execution_id)
        return c.final if c and c.final else None

    def pump(self, session: Any, force: bool = False) -> int:
        """Deliver due events (all of them when force=True). Returns how many were delivered."""
        now = time.monotonic()
        with self._lock:
            due = sorted((i for i in self._outbox if force or i.due <= now), key=lambda i: (i.due, i.seq))
            self._outbox = [i for i in self._outbox if i not in due]
        for item in due:
            if item.type == "tool":
                (self._tool_sink or _default_tool_sink)(session, item.data)
            else:
                (self._sink or _default_sink)(session, item.data)
        return len(due)

    def wallet_inr(self) -> float | None:
        return None  # simulated calls cost nothing

    def pending_events(self) -> int:
        return len(self._outbox)

    # -- scripting ------------------------------------------------------------
    def _push(self, exec_id: str, type_: str, data: dict, step: int) -> None:
        with self._lock:
            self._outbox.append(_Item(time.monotonic() + step * self.delay, next(self._seq), exec_id, type_, data))

    def _status(self, call: FakeCall, status: str, step: int, **extra: Any) -> dict:
        payload = {"id": call.exec_id, "status": status, "context_details": {"call_ref": call.user_data.get("call_ref")}, **extra}
        self._push(call.exec_id, "webhook", payload, step)
        return payload

    def _finish(self, call: FakeCall, step: int, *, transcript: str, extracted: dict | None, voicemail: bool = False,
                deliver: bool = True, duration: float = 40.0, cost: float = 5.0) -> None:
        payload = {
            "id": call.exec_id, "status": "completed", "conversation_duration": duration, "total_cost": cost,
            "transcript": transcript, "extracted_data": extracted, "answered_by_voice_mail": voicemail,
            "telephony_data": {"recording_url": f"https://fake.recordings/{call.exec_id}.mp3"},
            "context_details": {"call_ref": call.user_data.get("call_ref")},
        }
        call.final = payload
        if deliver:
            self._status(call, "call-disconnected", step)
            self._push(call.exec_id, "webhook", payload, step + 1)

    def _script(self, call: FakeCall) -> None:
        kind = call.kind
        key = call.user_data.get("supplier_key") or ""
        b = self.behaviour.get(key, "normal") if kind.startswith(("supplier", "confirm")) else "normal"
        if kind in ("approval", "callback", "intake"):
            b = {"yes": "normal", "no": "normal", "no-answer": "no-answer"}[self.owner] if kind == "approval" else "normal"
        self._status(call, "initiated", 1)
        if b in ("no-answer", "busy"):
            self._status(call, "ringing", 2)
            self._status(call, b, 3)
            call.final = {"id": call.exec_id, "status": b, "context_details": {"call_ref": call.user_data.get("call_ref")}}
            return
        self._status(call, "ringing", 2)
        self._status(call, "in-progress", 3)
        if b == "hang":
            return
        if b == "voicemail":
            self._finish(call, 4, transcript="[voicemail greeting]", extracted=None, voicemail=True, duration=12)
            return
        handler = getattr(self, f"_script_{kind}", None)
        if handler is None:
            self._finish(call, 4, transcript="ok", extracted=None)
            return
        handler(call, b)

    # -- supplier round 1 / 2 -----------------------------------------------------
    def _supplier_quote_rows(self, call: FakeCall, b: str) -> list[dict]:
        p = self.suppliers[call.user_data["supplier_key"]]
        q = p["quote"]
        wanted = call.user_data.get("items_list") or []
        rnd2 = call.kind == "supplier_r2"
        counter = {c["item"]: c["price"] for c in call.user_data.get("counter") or []}
        rows = []
        for it in wanted:
            name = it["name"]
            base_unit = "litre" if it["unit"] in ("litre", "l", "ltr") else it["unit"]
            price = q.get(name)
            if name == "onions" and self.use_split_variant and p.get("split_variant"):
                price = p["split_variant"]["onions"]
            avail = price is not None and b != "out_of_stock"
            if rnd2 and price is not None and name in counter:
                price = min(price, (p.get("round2") or {}).get("will_drop_to", {}).get(name, price))
            delivery = q.get("delivery")
            if b == "late":
                delivery = "09:30"
            row = {"item": name, "unit_price": str(price) if avail else None, "unit": base_unit if avail else None,
                   "available": avail, "delivery_time": delivery, "credit_days": q.get("credit_days") or 0,
                   "delivery_fee": q.get("delivery_fee") or 0,
                   "what_they_said": f"{name} {price} rupaye per {base_unit}" if avail else f"{name} nahi hai"}
            if rnd2 and (p.get("round2") or {}).get("credit_days_if_asked") and counter:
                row["credit_days"] = p["round2"]["credit_days_if_asked"]
            if b == "bad_unit" and avail:
                row.update(unit="petti", unit_price=str(price * 40), what_they_said=f"{name} {price * 40} rupaye petti")
            rows.append(row)
        return rows

    def _script_supplier(self, call: FakeCall, b: str) -> None:
        rows = self._supplier_quote_rows(call, b)
        extra_dnc = b == "do_not_call"
        for i, row in enumerate(rows):
            self._push(call.exec_id, "tool", {**row, "call_ref": call.user_data.get("call_ref"), "execution_id": call.exec_id}, 4)
        tr = "\n".join(f"supplier: {r['what_they_said']}" for r in rows)
        ext = {"Quotes": {"quotes_json": {"subjective": json.dumps(rows), "objective": None, "confidence": 0.9}}}
        if extra_dnc:
            ext["Quotes"]["do_not_call"] = {"subjective": "yes"}
        deliver = b != "lost_webhook"
        self._finish(call, 5, transcript=tr, extracted=ext, deliver=deliver)

    _script_supplier_r1 = _script_supplier
    _script_supplier_r2 = _script_supplier

    # -- owner calls -------------------------------------------------------------------
    def _script_approval(self, call: FakeCall, b: str) -> None:
        decision = "yes" if self.owner == "yes" else "no"
        ext = {"Approval": {"approval": {"subjective": json.dumps({"decision": decision})}}}
        self._finish(call, 4, transcript=f"agent: {call.user_data.get('summary', '')}\nowner: {decision}", extracted=ext)

    def _script_confirm(self, call: FakeCall, b: str) -> None:
        agreed = call.user_data.get("agreed") or []
        if b == "refuses_confirm":
            res = {"confirmed": False, "reason": "stock khatam"}
        else:
            qty = {a["item"]: a["quantity"] for a in agreed}
            if b == "wrong_quantity" and qty:
                k = next(iter(qty))
                qty[k] = qty[k] * 10
            res = {"confirmed": True, "quantities": qty, "total": call.user_data.get("expected_total"),
                   "delivery_time": call.user_data.get("delivery_time")}
        ext = {"Confirm": {"confirmed": {"subjective": json.dumps(res)}}}
        self._finish(call, 4, transcript=f"agent: confirm {agreed}\nsupplier: {res}", extracted=ext)

    def _script_intake(self, call: FakeCall, b: str) -> None:
        order = self.intake_order or {"items": [{"name": "onions", "quantity": 20, "unit": "kg"}, {"name": "oil", "quantity": 10, "unit": "litre"}],
                                      "deadline": "07:00", "budget": 1200}
        ext = {"Order": {"order_json": {"subjective": json.dumps(order)}}}
        self._finish(call, 4, transcript="owner: bees kilo pyaaz, das litre tel, subah saat baje tak", extracted=ext)

    def _script_callback(self, call: FakeCall, b: str) -> None:
        self._finish(call, 4, transcript=f"agent: {call.user_data.get('message', '')}", extracted=None)


def _default_sink(session: Any, payload: dict) -> None:  # replaced by the orchestrator at startup
    from app import orchestrator
    orchestrator.process_webhook(session, payload)


def _default_tool_sink(session: Any, data: dict) -> None:
    from app import orchestrator, services
    services.log_event(session, "tool", payload=data, execution_id=data.get("execution_id"))
    orchestrator.process_tool_quote(session, data)


# ----------------------------------------------------------------------- selection
_provider: Provider | None = None


def get_provider() -> Provider:
    global _provider
    if _provider is None:
        s = get_settings()
        _provider = FakeProvider(delay=s.fake_delay_seconds) if s.provider == "fake" else BolnaProvider(s)
    return _provider


def set_provider(p: Provider | None) -> None:
    global _provider
    _provider = p
