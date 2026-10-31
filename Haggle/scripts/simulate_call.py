#!/usr/bin/env python3
"""Replay a believable call against your RUNNING server: no Bolna, no phone, no cost.

Run (server must be up):  python scripts/simulate_call.py [--base http://localhost:8000]

Sends the same sequence Bolna would: status webhooks, two live `submit_quote` tool calls, a
contradicted quote, and a final `completed` webhook with the extraction. Then prints what
`/debug/calls` shows. Use it to rehearse the dashboard later and to prove the server works
before spending a rupee.
"""

import argparse
import json
import time
import uuid

import httpx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--token", default="", help="TOOL_SECRET, if set")
    ap.add_argument("--pause", type=float, default=0.5)
    a = ap.parse_args()

    ex = f"sim-{uuid.uuid4().hex[:8]}"
    ref = f"simref-{uuid.uuid4().hex[:8]}"
    headers = {"X-Dalaal-Token": a.token} if a.token else {}
    c = httpx.Client(base_url=a.base, timeout=10)

    def hook(status, **extra):
        r = c.post("/webhook/bolna", json={"id": ex, "status": status, "context_details": {"call_ref": ref}, **extra})
        print(f"webhook {status:<18} -> {r.status_code}")
        time.sleep(a.pause)

    def tool(**body):
        r = c.post("/tools/submit_quote", json={"call_ref": ref, **body}, headers=headers)
        print(f"submit_quote {body['item']:<8} {body['unit_price']!s:<14} -> {r.status_code} {r.json()}")
        time.sleep(a.pause)

    for st in ("queued", "initiated", "ringing", "in-progress"):
        hook(st)
    tool(item="onions", unit_price="pachchis rupaye", unit="kilo", available=True, delivery_time="07:00",
         credit_days="0", delivery_fee="0", what_they_said="pyaaz pachchis rupaye kilo")
    tool(item="oil", unit_price="52", unit="litre", delivery_time="07:00")  # misheard: really 62
    hook("call-disconnected")
    quotes = [
        {"item": "onions", "unit_price": "25", "unit": "kg", "available": True, "delivery_time": "07:00",
         "credit_days": 0, "delivery_fee": 0, "what_they_said": "pyaaz pachchis rupaye kilo"},
        {"item": "oil", "unit_price": "62", "unit": "litre", "available": True, "delivery_time": "07:00",
         "credit_days": 0, "delivery_fee": 0, "what_they_said": "tel bassath rupaye litre"},
    ]
    hook("completed", transcript="assistant: ...", total_cost=3.2, conversation_duration=48,
         telephony_data={"recording_url": "https://example.invalid/rec"},
         extracted_data={"Dalaal": {"quotes_json": {"subjective": json.dumps(quotes), "objective": None}}})
    hook("completed", transcript="REPLAY must change nothing")  # duplicate delivery

    print("\n/debug/calls:")
    print(json.dumps(c.get("/debug/calls").json()[0], indent=2, ensure_ascii=False))
    print("\nExpected: oil is 62 (confirmed, provisional=false), not the misheard 52.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
