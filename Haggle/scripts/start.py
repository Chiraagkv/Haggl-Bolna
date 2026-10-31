#!/usr/bin/env python3
"""One command to set up and run Dalaal. Nothing to edit by hand, nothing to do in the Bolna dashboard.

    python scripts/start.py                       # live: real calls through Bolna
    python scripts/start.py owner=+91... kumar=+91... ramesh=+91...   # first time, or to change numbers
    python scripts/start.py --fake                # rehearsal: simulated suppliers, no key, no credit

Live mode, in order:
  1. uses the project's .venv (creates it and installs requirements the first time)
  2. creates .env if missing and asks for BOLNA_API_KEY once; generates TOOL_SECRET
  3. saves the phone numbers you pass (they must already be verified in Bolna)
  4. starts a cloudflared (or ngrok) tunnel and writes its new URL to PUBLIC_BASE_URL
  5. creates any missing agent, re-pushes the full config of the others (webhook + submit_quote tool
     with the new URL), and creates their extractions          -> app/bolna_setup.py
  6. starts the server, checks the tunnel reaches it, prints the readiness list
  7. keeps running until Ctrl+C, then stops the server and the tunnel

Re-running after a restart is the same single command: a new tunnel URL is pushed to Bolna by step 5.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
VENV_PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _ensure_venv() -> None:
    """Re-run this script with the project's virtual environment, creating it if needed."""
    if Path(sys.prefix).resolve() == VENV.resolve():
        return
    if not VENV_PY.exists():
        print("First run: creating .venv and installing requirements (a minute or two)...")
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
        subprocess.check_call([str(VENV_PY), "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements-dev.txt")])
    os.execv(str(VENV_PY), [str(VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]])


_ensure_venv()
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import argparse  # noqa: E402
import getpass  # noqa: E402
import re  # noqa: E402
import secrets  # noqa: E402
import shutil  # noqa: E402
import signal  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

import httpx  # noqa: E402

from app import envfile  # noqa: E402

ENV = ROOT / ".env"
CLOUDFLARE_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def say(msg: str) -> None:
    print(msg, flush=True)


# ------------------------------------------------------------------------------- .env
def ensure_env(fake: bool) -> None:
    if not ENV.exists():
        ENV.write_text((ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
        say("Created .env from .env.example.")
    values = _read_env()
    updates: dict[str, str] = {}
    if not fake and not values.get("BOLNA_API_KEY"):
        key = getpass.getpass("Paste your Bolna API key (Bolna dashboard -> API Keys; typing is hidden): ").strip()
        if not key:
            raise SystemExit("No key given. For a rehearsal without Bolna run: python scripts/start.py --fake")
        updates["BOLNA_API_KEY"] = key
    if not values.get("TOOL_SECRET"):
        updates["TOOL_SECRET"] = secrets.token_urlsafe(24)
    if not fake and values.get("PROVIDER", "bolna") != "bolna":
        updates["PROVIDER"] = "bolna"
    if updates:
        envfile.set_values(ENV, updates)


def _read_env() -> dict[str, str]:
    out = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def settings():
    from app.config import get_settings
    get_settings.cache_clear()
    return get_settings()


# ------------------------------------------------------------------------------- numbers
def save_numbers(argv: list[str]) -> None:
    from app import seed
    langs, argv = seed.parse_language_args(argv)
    parsed, errors = seed.parse_number_args(argv)
    if errors:
        raise SystemExit("Nothing changed:\n  " + "\n  ".join(errors))
    if parsed:
        s = settings()
        kept = {n for n in s.verified_number_set if seed.E164.match(n)}
        envfile.set_values(ENV, {"VERIFIED_NUMBERS": ",".join(sorted(kept | {n for n in parsed.values() if n}))})
    subprocess.check_call([sys.executable, "scripts/seed_demo.py", *[f"{k}={v}" for k, v in parsed.items()],
                           *[f"{k}{seed.LANG_SUFFIX}={v}" for k, v in langs.items()]], cwd=ROOT)  # prints who has which number and language
    if not settings().verified_number_set:
        raise SystemExit("No phone numbers yet. Run once with the verified numbers, e.g.\n"
                         "  python scripts/start.py owner=+91XXXXXXXXXX kumar=+91XXXXXXXXXX ramesh=+91XXXXXXXXXX")


# ------------------------------------------------------------------------------- tunnel
def parse_cloudflare_url(line: str) -> str | None:
    m = CLOUDFLARE_URL.search(line)
    return m.group(0) if m else None


def start_tunnel(port: int) -> tuple[subprocess.Popen, str]:
    if shutil.which("cloudflared"):
        proc = subprocess.Popen(["cloudflared", "tunnel", "--no-autoupdate", "--url", f"http://localhost:{port}"],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        found: list[str] = []

        def read() -> None:
            for line in proc.stdout:  # type: ignore[union-attr]
                if not found and (url := parse_cloudflare_url(line)):
                    found.append(url)
        threading.Thread(target=read, daemon=True).start()  # keeps draining the pipe after the URL is found
        for _ in range(60):
            if found:
                return proc, found[0]
            if proc.poll() is not None:
                break
            time.sleep(0.5)
        proc.terminate()
        raise SystemExit("cloudflared did not print a tunnel URL within 30 s. Check your internet connection.")
    if shutil.which("ngrok"):
        proc = subprocess.Popen(["ngrok", "http", str(port), "--log", "stdout"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                tunnels = httpx.get("http://127.0.0.1:4040/api/tunnels", timeout=2).json().get("tunnels", [])
                url = next((t["public_url"] for t in tunnels if t.get("public_url", "").startswith("https://")), None)
                if url:
                    return proc, url
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        proc.terminate()
        raise SystemExit("ngrok did not report a tunnel URL. Run `ngrok config add-authtoken <token>` once.")
    raise SystemExit("No tunnel program found. Install one:\n  sudo pacman -S cloudflared      (Arch/CachyOS)\n"
                     "  or https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/")


def wait_for(url: str, seconds: int) -> bool:
    for _ in range(seconds * 2):
        try:
            if httpx.get(url, timeout=3).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


# ------------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("numbers", nargs="*", help="owner=+91... kumar=+91... ramesh=+91... (verified in Bolna); "
                                               "kumar.lang=kn sets the language a person's calls start in (hi, en, kn)")
    ap.add_argument("--fake", action="store_true", help="simulated suppliers: no key, no tunnel, no credit")
    ap.add_argument("--port", type=int, default=None, help="default 8000 (8001 with --fake)")
    args = ap.parse_args()
    port = args.port or (8001 if args.fake else 8000)
    children: list[subprocess.Popen] = []

    def stop(*_: object) -> None:
        for p in children:
            if p.poll() is None:
                p.terminate()
        for p in children:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        raise SystemExit(0)
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    ensure_env(args.fake)
    env = dict(os.environ)
    if args.fake:
        # Own database, so rehearsal orders never mix with real ones on the live board.
        env.update(PROVIDER="fake", FAKE_DELAY_SECONDS=env.get("FAKE_DELAY_SECONDS", "1.5"),
                   DATABASE_URL=env.get("DATABASE_URL", "sqlite:///./dalaal_rehearsal.db"))
        subprocess.check_call([sys.executable, "scripts/seed_demo.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL)
    else:
        say("1/4  phone numbers")
        save_numbers(args.numbers)
        say("2/4  tunnel")
        tunnel, url = start_tunnel(port)
        children.append(tunnel)
        envfile.set_values(ENV, {"PUBLIC_BASE_URL": url})
        say(f"     {url}")
        say("3/4  Bolna agents, tool and extractions")
        from app import bolna_setup
        from app.bolna_client import BolnaClient, BolnaError
        s = settings()
        try:
            client = BolnaClient()
            client.account()
        except BolnaError as e:
            for p in children:
                p.terminate()
            raise SystemExit(f"Bolna rejected the API key: {e}. Fix BOLNA_API_KEY in .env and run again.") from None
        ids, failed = bolna_setup.sync_agents(client, s, log=say)
        if ids:
            envfile.set_values(ENV, {bolna_setup.ENV_NAME[k]: v for k, v in ids.items()})
        if failed:
            say("     Some agents failed (exact error above). Fix bolna/supplier_agent.template.json and run again.")

    say(("4/4  " if not args.fake else "") + f"server on http://localhost:{port}")
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)], cwd=ROOT, env=env)
    children.append(server)
    if not wait_for(f"http://localhost:{port}/health", 30):
        say("The server did not start; its error is printed above.")
        stop()

    if not args.fake:
        s = settings()
        if not wait_for(s.public_base_url.rstrip("/") + "/health", 45):
            say("     WARNING: the tunnel does not reach the server yet (new tunnels can take a minute). Bolna's updates "
                "will not arrive until it does; /api/preflight?probe=true re-checks.")
        from app import db, preflight
        db.init_db()
        result = preflight.run(next(db.get_session()), s, probe=True)
        say("")
        for c in result["checks"]:
            say(f"  [{'ok' if c['ok'] else 'XX'}] {c['name']}: {c['detail']}" + (f"\n        -> {c['fix']}" if c["fix"] else ""))
        say("\nREADY for live calls." if result["ready"] else "\nNot ready: fix the XX lines above, then run this again.")

    mode = "SIMULATED suppliers (no calls, no credit)" if args.fake else "LIVE calls"
    say(f"\nOpen http://localhost:{port}  ·  {mode}  ·  Ctrl+C stops everything.\n")
    while True:
        for p in children:
            if p.poll() is not None:
                say(f"{'Server' if p is server else 'Tunnel'} stopped unexpectedly (exit {p.returncode}). Stopping.")
                stop()
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
