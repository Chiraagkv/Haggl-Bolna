#!/usr/bin/env python3
"""Tickets #7, #10, #11: place ONE test call to a verified teammate.

Run:
  python scripts/place_test_call.py --to +919876543210
  python scripts/place_test_call.py --to +919876543210 --wait      # also poll until it completes

Safety: refuses unless the number is in VERIFIED_NUMBERS and KILL_SWITCH is off. A test call costs
real wallet money, so use it sparingly. NOT run against the live API by the author.
"""

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import services  # noqa: E402
from app.bolna_client import BolnaClient, BolnaError  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import get_session, init_db  # noqa: E402
from app.safety import DialRefused, check_can_dial  # noqa: E402
from app.statuses import is_terminal  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", required=True, help="verified teammate number, E.164")
    ap.add_argument("--agent-id", default=None)
    ap.add_argument("--business", default="Priya's Cloud Kitchen")
    ap.add_argument("--items", default="20 kilo pyaaz aur 10 litre tel")
    ap.add_argument("--deadline", default="kal subah 7 baje tak")
    ap.add_argument("--wait", action="store_true", help="poll the execution until it finishes")
    args = ap.parse_args()

    s = get_settings()
    agent_id = args.agent_id or s.supplier_agent_id
    if not agent_id:
        print("No agent id. Pass --agent-id or set SUPPLIER_AGENT_ID in .env.")
        return 1
    try:
        check_can_dial(args.to, s)
    except DialRefused as e:
        print(f"Refused: {e}")
        return 1

    init_db()
    session = next(get_session())
    call_ref = f"test-{uuid.uuid4().hex[:12]}"
    call = services.get_or_create_call(session, call_ref=call_ref)

    client = BolnaClient()
    try:
        result = client.make_call(
            agent_id,
            args.to,
            user_data={
                "business_name": args.business,
                "items_spoken": args.items,
                "deadline_spoken": args.deadline,
                "call_ref": call_ref,
            },
        )
    except BolnaError as e:
        print(f"Bolna refused the call: {e}")
        return 1

    services.get_or_create_call(session, call_ref=call_ref, execution_id=result["execution_id"])
    services.log_event(session, "system", payload={"placed": result, "call_ref": call_ref},
                       execution_id=result["execution_id"])
    print(f"Call queued. execution_id={result['execution_id']}  call_ref={call_ref}")
    print("Watch it land:  GET /debug/calls  and  GET /debug/events  on your server.")

    if not args.wait:
        return 0

    print("Polling every 5s (Ctrl+C to stop)...")
    deadline = time.time() + 300
    last = None
    while time.time() < deadline:
        ex = client.get_execution(result["execution_id"])
        st = ex.get("status")
        if st != last:
            print(f"  status: {st}")
            last = st
        if is_terminal(st):
            if st == "completed":
                print(json.dumps({k: ex.get(k) for k in
                                  ("conversation_duration", "total_cost", "extracted_data", "transcript")},
                                 indent=2, ensure_ascii=False))
            return 0
        time.sleep(5)
    print("Timed out waiting for a terminal status.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
