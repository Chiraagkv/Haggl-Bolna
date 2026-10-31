#!/usr/bin/env python3
"""Create the Dalaal agents through the API (replaces create_supplier_agent.py).

Run:  python scripts/render_bolna_files.py && python scripts/create_agents.py [--only approval] [--force]

Posts build/agent_<kind>.json to POST /v2/agent (expects 201 with {agent_id}) for each kind whose
*_AGENT_ID is not already set in .env, and prints the lines to paste into .env. If Bolna rejects a
config its exact error is printed: fix bolna/supplier_agent.template.json (the synthesizer block
is the likeliest culprit) or build the agent in the dashboard and set its id by hand.
NOT run against the live API by the author: no key was available.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.bolna_client import BolnaClient, BolnaError  # noqa: E402
from app.config import get_settings  # noqa: E402

ENV_NAME = {"supplier_r1": "SUPPLIER_AGENT_ID", "supplier_r2": "SUPPLIER_R2_AGENT_ID", "approval": "APPROVAL_AGENT_ID",
            "confirm": "CONFIRM_AGENT_ID", "callback": "CALLBACK_AGENT_ID", "intake": "INTAKE_AGENT_ID"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=list(ENV_NAME), nargs="*")
    ap.add_argument("--write-env", action="store_true", help="also write the new ids into .env")
    ap.add_argument("--force", action="store_true", help="create even if the id is already set")
    args = ap.parse_args()
    s = get_settings()
    have = {"supplier_r1": s.supplier_agent_id, "supplier_r2": s.supplier_r2_agent_id, "approval": s.approval_agent_id,
            "confirm": s.confirm_agent_id, "callback": s.callback_agent_id, "intake": s.intake_agent_id}
    try:
        client = BolnaClient()
    except BolnaError as e:
        print(e)
        return 1
    lines, failed = [], 0
    for kind in args.only or ENV_NAME:
        if have[kind] and not args.force:
            print(f"{kind}: already set ({have[kind]}), skipping (use --force to create anyway)")
            continue
        path = ROOT / "build" / f"agent_{kind}.json"
        if not path.exists():
            print(f"{path} is missing. Run scripts/render_bolna_files.py first.")
            return 1
        try:
            res = client.create_agent(json.loads(path.read_text(encoding="utf-8")))
        except BolnaError as e:
            failed += 1
            print(f"{kind}: Bolna refused the config:\n  {e}")
            if e.body:
                print(json.dumps(e.body, indent=2, ensure_ascii=False))
            continue
        print(f"{kind}: created {res['agent_id']} (state: {res.get('state')})")
        lines.append(f"{ENV_NAME[kind]}={res['agent_id']}")
    if lines and args.write_env:
        from app import envfile
        envfile.set_values(ROOT / ".env", dict(l.split("=", 1) for l in lines))
        print("\nWrote the ids to .env. Restart the server.")
    if lines:
        print("\nAdd to .env:\n  " + "\n  ".join(lines))
        print("\nThen, in the Bolna dashboard: attach the submit_quote tool (build/submit_quote_tool.json) to the two supplier "
              "agents and create the extractions listed in bolna/extractions.md.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
