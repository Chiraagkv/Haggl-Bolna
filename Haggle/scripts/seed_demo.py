#!/usr/bin/env python3
"""Load the demo owner and suppliers, optionally pointing them at teammates' phones.

    python scripts/seed_demo.py
    python scripts/seed_demo.py owner=+919800000001 kumar=+919800000002 ramesh=+919800000003 gowda=+919800000004 lakshmi=+919800000005

Every number you pass must also be in VERIFIED_NUMBERS in .env (and verified in Bolna on a trial
account). The app refuses to dial anything else.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app import db, seed  # noqa: E402
from app.models import Supplier  # noqa: E402


def main(argv: list[str]) -> int:
    langs, argv = seed.parse_language_args(argv)
    numbers, errors = seed.parse_number_args(argv)
    if errors:
        print("Nothing changed:\n  " + "\n  ".join(errors))
        return 1
    db.init_db()
    session = next(db.get_session())
    owner = seed.ensure_demo_data(session)
    for who, number in numbers.items():
        number = number or None  # `kumar=` clears the number: that supplier is skipped
        if who == "owner":
            owner.phone = number
        else:
            sup = session.scalar(select(Supplier).where(Supplier.owner_id == owner.id, Supplier.key == who))
            if sup is None:
                print(f"no supplier {who!r}")
                return 1
            sup.phone = number
        print(f"{who} -> {number}")
    for who, lang in langs.items():  # `kumar.lang=kn`: the language this person's calls start in
        target = owner if who == "owner" else session.scalar(select(Supplier).where(Supplier.owner_id == owner.id, Supplier.key == who))
        if target is None:
            print(f"no supplier {who!r}")
            return 1
        target.language = lang
        print(f"{who} speaks {lang}")
    session.commit()
    print(f"Owner {owner.name}: {owner.phone} ({owner.language})")
    for sup in session.scalars(select(Supplier).where(Supplier.owner_id == owner.id)):
        print(f"  {sup.key:8} {sup.name:22} {sup.phone}  ({sup.language})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
