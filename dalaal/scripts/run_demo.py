#!/usr/bin/env python3
"""Run the whole product once, offline, with fake suppliers, and print what happened.

    python scripts/run_demo.py                  # the happy path
    python scripts/run_demo.py --fail kumar=no-answer gowda=voicemail
    python scripts/run_demo.py --budget 1000 --owner no
    python scripts/run_demo.py --split          # Lakshmi's cheap onions -> split basket

Uses an in-memory database; nothing is dialed and no key is needed.
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.update(DATABASE_URL="sqlite:///:memory:", PROVIDER="fake", FAKE_DELAY_SECONDS="0", BOLNA_API_KEY="")

from app import db, metrics, orchestrator as orc, orders, providers, seed  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fail", nargs="*", default=[], help="supplier=behaviour (no-answer, voicemail, late, refuses_confirm, ...)")
    ap.add_argument("--budget", type=float)
    ap.add_argument("--owner", default="yes", choices=["yes", "no", "no-answer"])
    ap.add_argument("--split", action="store_true")
    args = ap.parse_args()

    db.init_db()
    session = next(db.get_session())
    fake = providers.FakeProvider(delay=0)
    providers.set_provider(fake)
    fake.owner, fake.use_split_variant = args.owner, args.split
    for item in args.fail:
        k, v = item.split("=")
        fake.behaviour[k] = v
    owner = seed.ensure_demo_data(session)
    spec = seed.demo_order_spec()
    order = orc.create_order(session, owner.id, spec["items"], spec["deadline"], args.budget or spec["budget"])
    orc.start_order(session, order.id)
    orc.run_until_idle(session, fake)
    session.expire_all()
    order = orders.get_order(session, order.id)

    for e in orders.events_after(session, order.id, 0, 5000):
        p = e.payload or {}
        if e.kind == "state":
            print(f"  -> {p['state']}{' (' + p['reason'] + ')' if p.get('reason') else ''}")
        elif e.kind == "quote":
            print(f"       quote {p['supplier']}: {p['item']} {p['price']}/{p['unit']}{' (live)' if p['provisional'] else ''}")
        elif e.kind in ("notify", "rebook", "confirm_failed", "guard", "voicemail", "do_not_call"):
            print(f"       {e.kind}: {p}")
    print(f"\nState: {order.state}  {order.failure_reason or ''}")
    if order.booked_total is not None:
        print(f"Booked Rs {order.booked_total:,.0f} with {sorted(set(order.assignments.values()))}; baseline Rs {order.baseline_total:,.0f} "
              f"({order.baseline_kind}); saved Rs {order.savings}; phone time saved {order.time_saved_min} min; call cost Rs {order.cost_incurred}")
    print("Calls placed:", len(fake.placed))
    return 0 if order.state in (orders.REPORTED, orders.FAILED) else 1


if __name__ == "__main__":
    raise SystemExit(main())
