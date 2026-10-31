#!/usr/bin/env python3
"""Setup only (no tunnel, no server). Prefer scripts/start.py, which does this and runs everything.

    1. put BOLNA_API_KEY (and PUBLIC_BASE_URL from scripts/tunnel.sh) in .env
    2. python scripts/go_live.py owner=+91... kumar=+91... ramesh=+91...     (teammates' verified numbers)

It: writes VERIFIED_NUMBERS and a TOOL_SECRET into .env if missing, seeds the demo data with your numbers,
renders the Bolna files, creates any missing agents (writing their ids to .env), then prints the preflight
list: what is ready, what is not, and the two things only the Bolna dashboard can do.
Safe to run again; existing agent ids are never replaced.
"""

import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import bolna_setup, db, envfile, preflight, seed  # noqa: E402
from app.bolna_client import BolnaClient, BolnaError  # noqa: E402
from app.config import get_settings  # noqa: E402


def sh(*args: str) -> int:
    return subprocess.call([sys.executable, *args], cwd=ROOT)


def main(argv: list[str]) -> int:
    env = ROOT / ".env"
    if not env.exists():
        env.write_text((ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
        print("Created .env from .env.example. Put BOLNA_API_KEY and PUBLIC_BASE_URL in it, then run this again.")
        return 1
    s = get_settings()
    langs, rest = seed.parse_language_args(argv)
    parsed, errors = seed.parse_number_args(rest)
    if errors:
        print("Nothing changed:\n  " + "\n  ".join(errors))
        return 1
    argv = [f"{who}={n}" for who, n in parsed.items()] + [f"{k}{seed.LANG_SUFFIX}={v}" for k, v in langs.items()]
    numbers = [n for n in parsed.values() if n]
    updates = {}
    if not s.tool_secret:
        updates["TOOL_SECRET"] = secrets.token_urlsafe(24)
    if numbers:
        kept = {n for n in s.verified_number_set if seed.E164.match(n)}  # drops junk such as a bare "+91"
        updates["VERIFIED_NUMBERS"] = ",".join(sorted(set(numbers) | kept))
    if updates:
        envfile.set_values(env, updates)
        get_settings.cache_clear()
        print("Updated .env:", ", ".join(k for k in updates if k != "TOOL_SECRET") + (" (TOOL_SECRET generated)" if "TOOL_SECRET" in updates else ""))
    s = get_settings()
    if not s.has_bolna_key or not s.public_base_url:
        print("BOLNA_API_KEY and PUBLIC_BASE_URL must be set in .env first (scripts/tunnel.sh gives the URL).")
        return 1
    print("\n== seeding ==")
    sh("scripts/seed_demo.py", *argv)
    print("\n== rendering Bolna files ==")
    if sh("scripts/render_bolna_files.py"):
        return 1
    print("\n== Bolna agents, tool and extractions ==")
    try:
        ids, _ = bolna_setup.sync_agents(BolnaClient(), get_settings())
    except BolnaError as e:
        print(f"Bolna: {e}")
        return 1
    if ids:
        envfile.set_values(env, {bolna_setup.ENV_NAME[k]: v for k, v in ids.items()})
    get_settings.cache_clear()
    db.init_db()
    result = preflight.run(next(db.get_session()), get_settings(), probe=True)
    print("\n== preflight ==")
    for c in result["checks"]:
        print(f"  [{'ok' if c['ok'] else 'XX'}] {c['name']}: {c['detail']}" + (f"\n        -> {c['fix']}" if c["fix"] else ""))
    for m in result["manual_steps"]:
        print("  [ ] " + m)
    print("\nREADY for a live test." if result["ready"] else "\nNot ready yet: fix the XX lines above and run this again.")
    print("Then: uvicorn app.main:app --port 8000   and open http://localhost:8000"
          "\n(Simpler: python scripts/start.py does all of this plus the tunnel and the server.)")
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
