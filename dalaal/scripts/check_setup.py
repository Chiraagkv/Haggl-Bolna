#!/usr/bin/env python3
"""Phase 0 setup check (ticket #1 and #3).

Run:  python scripts/check_setup.py

Reads your real concurrency limit and wallet from Bolna and prints a block to paste into
NOTES.md. Needs BOLNA_API_KEY in .env. Places no calls and costs nothing.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.bolna_account import fetch_account, make_client, notes_snippet  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import db_ok  # noqa: E402


def main() -> int:
    s = get_settings()
    print("Dalaal setup check\n")
    print(f"Database reachable : {'yes' if db_ok() else 'NO  (check DATABASE_URL)'}")
    print(f"Bolna key set      : {'yes' if s.has_bolna_key else 'NO  (set BOLNA_API_KEY in .env)'}")
    print(f"Public URL set     : {'yes' if s.public_base_url else 'no   (run scripts/tunnel.sh, then set PUBLIC_BASE_URL)'}")

    if not s.has_bolna_key:
        return 1

    try:
        with make_client(s.bolna_api_key, s.bolna_base_url) as client:
            info = fetch_account(client)
    except PermissionError as e:
        print(f"\n{e}")
        return 1
    except httpx.HTTPError as e:
        print(f"\nCould not reach Bolna: {e}")
        return 1

    print("\nPaste this into NOTES.md under 'Account limits':\n")
    print(notes_snippet(info, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")))
    if info.concurrency is not None and info.concurrency != s.concurrency_limit:
        print(
            f"Note: CONCURRENCY_LIMIT in .env is {s.concurrency_limit} but Bolna reports "
            f"{info.concurrency}. Update .env so the dialer uses the real number."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
