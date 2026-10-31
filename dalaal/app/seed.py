"""Load the demo owner and suppliers from data/personas.json (idempotent).

The reliability histories are typed in by hand for the demo, and the team says so on stage.
Phone numbers in the file are placeholders: replace them with verified teammate numbers.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Owner, Supplier

PERSONAS_PATH = Path(__file__).resolve().parent.parent / "data" / "personas.json"


def load_personas(path: Path | None = None) -> dict:
    return json.loads((path or PERSONAS_PATH).read_text(encoding="utf-8"))


def ensure_demo_data(session: Session, path: Path | None = None) -> Owner:
    data = load_personas(path)
    o = data["owner"]
    owner = session.scalar(select(Owner).where(Owner.business_name == o["business_name"]))
    if owner is None:
        owner = Owner(
            name=o["name"], phone=o.get("phone"), business_name=o["business_name"], language=o.get("language", "hi"),
            usual_prices=o.get("usual_prices"), manual_minutes_per_order=float(o.get("manual_minutes_per_order", 15)),
        )
        session.add(owner)
        session.commit()
    for s in data["suppliers"]:
        existing = session.scalar(select(Supplier).where(Supplier.owner_id == owner.id, Supplier.key == s["key"]))
        if existing is None:
            items = [k for k, v in s["quote"].items() if k not in ("delivery", "credit_days", "delivery_fee") and v is not None]
            session.add(
                Supplier(
                    owner_id=owner.id, key=s["key"], name=s["name"], phone=s.get("phone"), language=s.get("language", "hi"),
                    items=items, on_time_count=s["history"]["on_time"], late_count=s["history"]["late"],
                    credit_days_usual=s["quote"].get("credit_days"), is_usual=bool(s.get("is_usual", False)),
                )
            )
    session.commit()
    return owner


E164 = re.compile(r"^\+\d{10,15}$")


LANG_SUFFIX = ".lang"


def parse_language_args(argv: list[str]) -> tuple[dict[str, str], list[str]]:
    """Split `kumar.lang=kn` style arguments off the rest: ({"kumar": "kn"}, remaining argv)."""
    langs, rest = {}, []
    for arg in argv:
        who, _, value = arg.partition("=")
        if who.endswith(LANG_SUFFIX) and value:
            langs[who[: -len(LANG_SUFFIX)]] = value.strip().lower()
        else:
            rest.append(arg)
    return langs, rest


def parse_number_args(argv: list[str]) -> tuple[dict[str, str], list[str]]:
    """`owner=+91 93115 09800 kumar=+91...` -> ({"owner": "+919311509800", ...}, errors).

    A shell splits a number typed with spaces into several arguments, so pieces without `=` are glued
    back onto the previous one. Spaces and dashes are dropped; anything not E.164 is an error, never saved.
    `kumar=` (empty) is allowed: it clears that supplier's number.
    """
    pairs: list[list[str]] = []
    errors: list[str] = []
    for arg in argv:
        if "=" in arg:
            pairs.append(arg.split("=", 1))
        elif pairs:
            pairs[-1][1] += arg
        else:
            errors.append(f"{arg!r}: expected name=+91...")
    out: dict[str, str] = {}
    for who, raw in pairs:
        number = re.sub(r"[\s\-()]", "", raw)
        if number and not E164.match(number):
            errors.append(f"{who}={raw!r}: not a full phone number (want +91 and 10 digits, e.g. +919311509800)")
            continue
        out[who] = number
    return out, errors


def demo_order_spec(path: Path | None = None) -> dict:
    return load_personas(path)["owner"]["demo_order"]
