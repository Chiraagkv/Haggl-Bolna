#!/usr/bin/env python3
"""Push prompt and welcome-message changes to the agents that already exist on Bolna.

Run:  python scripts/render_bolna_files.py && python scripts/update_agents.py [--only supplier_r1 ...]

Uses PATCH /v2/agent/{id}, which keeps everything it is not given: the submit_quote tool and the
extractions you attached in the dashboard survive. (create_agents.py --force would make NEW agents
without them.) PATCH cannot change call_terminate or the transcriber: change those in the dashboard.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.bolna_client import BolnaClient, BolnaError  # noqa: E402
from app.config import get_settings  # noqa: E402
from scripts.create_agents import ENV_NAME  # noqa: E402


def patch_body(rendered: dict) -> dict:
    cfg = rendered["agent_config"]
    return {
        "agent_config": {k: cfg[k] for k in ("agent_name", "agent_welcome_message", "webhook_url") if k in cfg},
        "agent_prompts": rendered["agent_prompts"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=list(ENV_NAME), nargs="*")
    args = ap.parse_args()
    s = get_settings()
    try:
        client = BolnaClient()
    except BolnaError as e:
        print(e)
        return 1
    failed = 0
    for kind in args.only or ENV_NAME:
        agent_id = getattr(s, ENV_NAME[kind].lower())
        if not agent_id:
            print(f"{kind}: no {ENV_NAME[kind]} in .env, skipping (create it with create_agents.py)")
            continue
        path = ROOT / "build" / f"agent_{kind}.json"
        if not path.exists():
            print(f"{path} is missing. Run scripts/render_bolna_files.py first.")
            return 1
        try:
            client.patch_agent(agent_id, patch_body(json.loads(path.read_text(encoding="utf-8"))))
        except BolnaError as e:
            failed += 1
            print(f"{kind}: Bolna refused the update:\n  {e}")
            continue
        print(f"{kind}: updated {agent_id}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
