"""'Am I ready to go live?' in one list (used by GET /api/preflight and scripts/go_live.py).

Each check says what is wrong and exactly what to do. Nothing here places a call.
"""

from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import db_ok
from app.models import Owner, Supplier


def _c(name: str, ok: bool, detail: str, fix: str = "", required: bool = True) -> dict:
    return {"name": name, "ok": ok, "detail": detail, "fix": "" if ok else fix, "required": required}


def run(session: Session, s: Settings, probe: bool = False) -> dict:
    live = s.provider == "bolna"
    checks = [
        _c("database", db_ok(), s.database_url.split("@")[-1], "check DATABASE_URL"),
        _c("kill switch off", not s.kill_switch, "calls allowed" if not s.kill_switch else "KILL_SWITCH=true", "set KILL_SWITCH=false"),
    ]
    if not live:
        checks.append(_c("provider", True, "PROVIDER=fake: simulated suppliers, nothing is dialed", required=False))
        return _summary(checks, live)
    checks += [
        _c("provider", True, "PROVIDER=bolna: real calls"),
        _c("Bolna API key", s.has_bolna_key, "set" if s.has_bolna_key else "empty", "put BOLNA_API_KEY in .env"),
        _c("public URL", bool(s.public_base_url), s.public_base_url or "empty",
           "run scripts/tunnel.sh and set PUBLIC_BASE_URL in .env"),
        _c("tool secret", bool(s.tool_secret), "set" if s.tool_secret else "empty (anyone can post quotes)",
           "set TOOL_SECRET to any long random string", required=False),
    ]
    for label, value, req in (("supplier agent (round 1)", s.supplier_agent_id, True), ("booking-confirmation agent", s.confirm_agent_id, True),
                              ("owner approval agent", s.approval_agent_id, True), ("owner callback agent", s.callback_agent_id, True),
                              ("round-2 agent", s.supplier_r2_agent_id, False), ("intake agent", s.intake_agent_id, False)):
        note = "round 1 agent is reused" if (label == "round-2 agent" and not value and s.supplier_agent_id) else ""
        checks.append(_c(label, bool(value) or bool(note), value or note or "missing", "run scripts/go_live.py (creates agents) or set the id in .env", req))
    verified = s.verified_number_set
    checks.append(_c("verified numbers", bool(verified) or not s.require_verified_numbers, f"{len(verified)} listed",
                     "put teammates' verified numbers in VERIFIED_NUMBERS (comma separated, +91...)"))
    owner = session.scalar(select(Owner).order_by(Owner.id))
    sups = list(session.scalars(select(Supplier))) if owner else []
    if owner is None:
        checks.append(_c("seeded data", False, "no owner/suppliers", "python scripts/seed_demo.py owner=+91... kumar=+91... ..."))
    else:
        ophone = s.owner_phone_override or owner.phone or ""
        checks.append(_c("owner phone is dialable", bool(ophone) and (ophone in verified or not s.require_verified_numbers), ophone or "none",
                         "seed_demo.py owner=+91... and add it to VERIFIED_NUMBERS"))
        ok_sups = [x.key for x in sups if x.phone and (x.phone in verified or not s.require_verified_numbers) and not x.do_not_call]
        checks.append(_c("suppliers that can be called", len(ok_sups) >= 1, ", ".join(ok_sups) or "none",
                         "seed_demo.py kumar=+91... (others can stay as they are: they are skipped, not dialed)"))
    if probe and s.public_base_url:
        try:
            r = httpx.get(s.public_base_url.rstrip("/") + "/health", timeout=6)
            checks.append(_c("tunnel reaches this server", r.status_code == 200, f"HTTP {r.status_code}", "start the tunnel and uvicorn"))
        except Exception as e:  # noqa: BLE001
            checks.append(_c("tunnel reaches this server", False, str(e)[:100], "start the tunnel and uvicorn"))
    return _summary(checks, live)


def _summary(checks: list[dict], live: bool) -> dict:
    ready = all(c["ok"] for c in checks if c["required"])
    manual: list[str] = []  # the tool and extractions are created through the API now (app/bolna_setup.py)
    return {"ready": ready, "live": live, "checks": checks, "manual_steps": manual}
