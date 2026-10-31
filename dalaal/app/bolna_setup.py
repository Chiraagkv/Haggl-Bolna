"""Everything the Bolna dashboard used to do, done through the API (used by scripts/start.py and go_live.py).

  render_tool / render_agents   the six agent configs from bolna/*.template.json + prompts, with the
                                submit_quote tool built in (tools_config.api_tools) for the supplier agents
  sync_agents                   create an agent if its id is missing or gone, otherwise PUT the whole
                                config again (so a new tunnel URL reaches the webhook AND the tool)
  ensure_extractions            create the named extractions (Bolna "dispositions") an agent is missing

Verified live on 2026-10-30: a custom_task tool in api_tools is stored as sent (headers included), and
POST /dispositions/bulk creates and links extractions. Nothing here places a call or spends credit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from app.bolna_client import BolnaClient, BolnaError
from app.config import Settings

ROOT = Path(__file__).resolve().parent.parent
BOLNA = ROOT / "bolna"

# kind -> (prompt file, agent name, welcome message per language, max call seconds)
# 60 s keeps every call inside one billed minute: Bolna rounds telephony up to the minute, so 61 s costs
# as much as 120 s. Only intake gets longer, because the owner has to list the whole order.
AGENTS = {
    "supplier_r1": ("supplier_round1.md", "Dalaal supplier agent (round 1)", {
        "hi": "Namaste, main {business_name} ka automated assistant hoon. Aaj ka bhaav poochna tha.",
        "en": "Hello, I'm an automated assistant calling for {business_name}. I'd like today's prices, please.",
        "kn": "ನಮಸ್ಕಾರ, ನಾನು {business_name} ಪರವಾಗಿ ಕರೆ ಮಾಡುತ್ತಿರುವ ಸ್ವಯಂಚಾಲಿತ ಸಹಾಯಕ. ಇವತ್ತಿನ ದರ ಕೇಳಬೇಕಿತ್ತು."}, 60),
    "supplier_r2": ("supplier_round2.md", "Dalaal supplier agent (round 2, counter-offer)", {
        "hi": "Namaste! Main {business_name} ki taraf se automated assistant bol raha hoon. Thodi der pehle aapse baat hui thi.",
        "en": "Hello, I'm the automated assistant for {business_name}. We spoke a few minutes ago.",
        "kn": "ನಮಸ್ಕಾರ, ನಾನು {business_name} ಸ್ವಯಂಚಾಲಿತ ಸಹಾಯಕ. ಸ್ವಲ್ಪ ಹೊತ್ತಿನ ಹಿಂದೆ ಮಾತಾಡಿದ್ದೆವು."}, 60),
    "approval": ("owner_approval.md", "Dalaal owner approval", {
        "hi": "Namaste {owner_name} ji, main Dalaal bol raha hoon, automated assistant. Ek order ke baare mein aapki haan chahiye.",
        "en": "Hello {owner_name}, this is Dalaal, your automated assistant. I need your yes on an order.",
        "kn": "ನಮಸ್ಕಾರ {owner_name}, ನಾನು ದಲಾಲ್, ಸ್ವಯಂಚಾಲಿತ ಸಹಾಯಕ. ಒಂದು ಆರ್ಡರ್‌ಗೆ ನಿಮ್ಮ ಒಪ್ಪಿಗೆ ಬೇಕು."}, 60),
    "confirm": ("supplier_confirm.md", "Dalaal booking confirmation", {
        "hi": "Namaste! Main {business_name} ki taraf se automated assistant bol raha hoon. Ek order pakka karna hai.",
        "en": "Hello, I'm the automated assistant for {business_name}, calling to place an order.",
        "kn": "ನಮಸ್ಕಾರ, ನಾನು {business_name} ಸ್ವಯಂಚಾಲಿತ ಸಹಾಯಕ. ಒಂದು ಆರ್ಡರ್ ಖಚಿತಪಡಿಸಬೇಕಿದೆ."}, 60),
    "intake": ("owner_intake.md", "Dalaal owner intake", {
        "hi": "Namaste {owner_name} ji, main Dalaal bol raha hoon, automated assistant. Bataiye, kya mangwana hai?",
        "en": "Hello {owner_name}, this is Dalaal, your automated assistant. What would you like to order?",
        "kn": "ನಮಸ್ಕಾರ {owner_name}, ನಾನು ದಲಾಲ್, ಸ್ವಯಂಚಾಲಿತ ಸಹಾಯಕ. ಏನು ತರಿಸಬೇಕು ಹೇಳಿ?"}, 90),
    "callback": ("owner_callback.md", "Dalaal owner report", {
        "hi": "Namaste {owner_name} ji, main Dalaal bol raha hoon, automated assistant. Aapke order ki khabar hai.",
        "en": "Hello {owner_name}, this is Dalaal, your automated assistant, with news about your order.",
        "kn": "ನಮಸ್ಕಾರ {owner_name}, ನಾನು ದಲಾಲ್, ಸ್ವಯಂಚಾಲಿತ ಸಹಾಯಕ. ನಿಮ್ಮ ಆರ್ಡರ್ ಬಗ್ಗೆ ಸುದ್ದಿ ಇದೆ."}, 60),
}
# Every agent speaks these. Bolna switches by itself when the other person switches (multilingual_config,
# trigger "requested_or_auto_detected"); a call STARTS in the person's language via user_data.agent_language.
LANGUAGES = {"hi": "Hindi", "en": "English", "kn": "Kannada"}
DEFAULT_LANGUAGE = "hi"
LANGUAGE_NOTE = ("\n\nLANGUAGE: speak {name} now{script}. The *_spoken values above are written in Hindi: say them naturally in "
                 "{name}, keeping every number exactly the same. Keep the same turns and the same time budget.")
SCRIPT = {"hi": " (Hindi or Hinglish, as they speak)", "en": " (simple Indian English)", "kn": " (in Kannada script)"}


def call_language(code: str | None) -> str:
    """The language a call starts in: the person's own if the agents speak it, else Hindi."""
    code = (code or "").strip().lower()
    return code if code in LANGUAGES else DEFAULT_LANGUAGE


def multilingual_config(prompt: str, welcome: dict[str, str], synthesizer: dict) -> dict:
    """Bolna's multilingual_config: one transcriber language, voice and prompt per language, same Sarvam voice."""
    pc = synthesizer["provider_config"]
    return {
        "enabled": True,
        "active_language": DEFAULT_LANGUAGE,
        "language_switch_trigger": "requested_or_auto_detected",
        "languages": {
            code: {
                "transcriber": {"language": code},
                "synthesizer": {"provider": synthesizer["provider"],
                                "provider_config": {"voice": pc["voice"], "voice_id": pc["voice_id"], "model": pc["model"], "language": code}},
                "system_prompt": prompt + LANGUAGE_NOTE.format(name=name, script=SCRIPT[code]),
                "welcome_message": welcome[code],
            }
            for code, name in LANGUAGES.items()
        },
    }


ENV_NAME = {"supplier_r1": "SUPPLIER_AGENT_ID", "supplier_r2": "SUPPLIER_R2_AGENT_ID", "approval": "APPROVAL_AGENT_ID",
            "confirm": "CONFIRM_AGENT_ID", "callback": "CALLBACK_AGENT_ID", "intake": "INTAKE_AGENT_ID"}
TOOL_KINDS = ("supplier_r1", "supplier_r2")


def strip_comments(obj):
    """Remove keys that start with an underscore (documentation only)."""
    if isinstance(obj, dict):
        return {k: strip_comments(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [strip_comments(v) for v in obj]
    return obj


def _fill(text: str, values: dict[str, str]) -> str:
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def render_tool(s: Settings) -> dict:
    """submit_quote in the dashboard's custom-function shape (what build/submit_quote_tool.json holds)."""
    text = (BOLNA / "submit_quote_tool.template.json").read_text(encoding="utf-8")
    return strip_comments(json.loads(_fill(text, {"PUBLIC_BASE_URL": s.public_base_url.rstrip("/"), "TOOL_SECRET": s.tool_secret})))


def api_tools(tool: dict) -> dict:
    """The same tool as the agent API wants it: the definition in `tools`, the HTTP call in `tools_params`."""
    v = tool["value"]
    return {
        "tools": [{k: tool[k] for k in ("name", "description", "pre_call_message", "parameters")} | {"key": tool["key"]}],
        "tools_params": {tool["name"]: {"method": v["method"], "url": v["url"], "api_token": v.get("api_token"),
                                        "param": json.dumps(v["param"]), "headers": v.get("headers") or {}}},
    }


def render_agents(s: Settings) -> dict[str, dict]:
    base = s.public_base_url.rstrip("/")
    template = (BOLNA / "supplier_agent.template.json").read_text(encoding="utf-8")
    tools = api_tools(render_tool(s))
    out = {}
    for kind, (prompt_file, name, welcome, seconds) in AGENTS.items():
        agent = json.loads(template)
        cfg = agent["agent_config"]
        cfg["agent_name"], cfg["agent_welcome_message"] = name, welcome[DEFAULT_LANGUAGE]
        task = cfg["tasks"][0]
        task["task_config"]["call_terminate"] = seconds
        if kind in TOOL_KINDS:
            task["tools_config"]["api_tools"] = tools
        prompt = (BOLNA / "prompts" / prompt_file).read_text(encoding="utf-8").strip()
        agent["agent_prompts"]["task_1"]["system_prompt"] = prompt
        task["tools_config"]["multilingual_config"] = multilingual_config(prompt, welcome, task["tools_config"]["synthesizer"])
        out[kind] = strip_comments(json.loads(_fill(json.dumps(agent), {"PUBLIC_BASE_URL": base})))
    return out


def load_extractions() -> dict:
    return json.loads((BOLNA / "extractions.json").read_text(encoding="utf-8"))


def _linked_ids(dispositions) -> set[str]:
    """GET /v2/agent/{id} lists linked dispositions as bare ids (seen live); accept objects too."""
    return {str(d.get("id") if isinstance(d, dict) else d) for d in dispositions or []}


def ensure_extractions(client: BolnaClient, agent_id: str, kind: str, spec: dict | None = None) -> list[str]:
    """Make this agent's extractions match bolna/extractions.json. Returns the names (re)created.

    Matched by name. A duplicate is deleted; one whose question no longer matches the repo is replaced.
    Extractions Bolna links by itself (not in the account's own list) are left alone."""
    spec = spec or load_extractions()
    wanted = spec["by_kind"].get(kind) or []
    linked = _linked_ids(client.get_agent(agent_id).get("dispositions"))
    mine: dict[str, list[dict]] = {}
    for d in sorted(client.list_dispositions(), key=lambda d: d.get("created_at") or ""):
        if str(d.get("id")) in linked:
            mine.setdefault(d.get("name"), []).append(d)
    create = []
    for name in wanted:
        rows = mine.get(name, [])
        keep = rows[0] if rows and rows[0].get("question") == spec["questions"][name] else None
        for d in rows:
            if d is not keep:
                client.delete_disposition(d["id"])
        if keep is None:
            create.append(name)
    if create:
        client.create_dispositions(agent_id, [
            {"name": n, "question": spec["questions"][n], "category": spec["category"], "is_subjective": True, "subjective_type": "text"}
            for n in create])
    return create


def sync_agents(client: BolnaClient, s: Settings, log: Callable[[str], None] = print) -> tuple[dict[str, str], int]:
    """Make the six agents on Bolna match this repo. Returns ({kind: agent_id}, number of failures).

    An agent whose id is in .env is updated in place (PUT replaces its whole config, which is fine:
    everything about it lives in this repo now). A missing or deleted one is created."""
    configs = render_agents(s)
    spec = load_extractions()
    ids, failed = {}, 0
    for kind, cfg in configs.items():
        agent_id = getattr(s, ENV_NAME[kind].lower())
        try:
            existing = None
            if agent_id:
                try:
                    existing = client.get_agent(agent_id)
                except BolnaError as e:
                    if e.status_code not in (400, 404):
                        raise
            if existing is not None:
                client.update_agent(agent_id, cfg)
                action = "updated"
            else:
                agent_id = client.create_agent(cfg)["agent_id"]
                action = "created"
            made = ensure_extractions(client, agent_id, kind, spec)  # re-read: never trust the pre-PUT copy
            ids[kind] = agent_id
            log(f"  {kind:12} {action} {agent_id}" + (f" + extractions {', '.join(made)}" if made else ""))
        except BolnaError as e:
            failed += 1
            log(f"  {kind:12} FAILED: {e}")
    return ids, failed
