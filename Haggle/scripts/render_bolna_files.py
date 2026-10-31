#!/usr/bin/env python3
"""Write the rendered Bolna configs to build/ (for reading, or pasting into the dashboard by hand).

Run:  python scripts/render_bolna_files.py

You normally do not need this: scripts/start.py renders and pushes everything itself. Writes
build/submit_quote_tool.json and one build/agent_<kind>.json per agent (the supplier agents already
contain the tool). Needs PUBLIC_BASE_URL.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import bolna_setup  # noqa: E402
from app.config import get_settings  # noqa: E402

AGENTS = bolna_setup.AGENTS  # kept for older imports


def main() -> int:
    s = get_settings()
    if not s.public_base_url:
        print("PUBLIC_BASE_URL is empty. Run scripts/start.py (it sets it), or scripts/tunnel.sh and set it in .env.")
        return 1
    out = ROOT / "build"
    out.mkdir(exist_ok=True)
    for kind, agent in bolna_setup.render_agents(s).items():
        (out / f"agent_{kind}.json").write_text(json.dumps(agent, indent=2, ensure_ascii=False))
        print(f"Wrote {out / f'agent_{kind}.json'}")
    (out / "submit_quote_tool.json").write_text(json.dumps(bolna_setup.render_tool(s), indent=2, ensure_ascii=False))
    print(f"Wrote {out / 'submit_quote_tool.json'}")
    if not s.tool_secret:
        print("Warning: TOOL_SECRET is empty, so /tools/submit_quote accepts anyone. Set one before real tests.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
