import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_script():
    spec = importlib.util.spec_from_file_location("render_bolna_files", ROOT / "scripts" / "render_bolna_files.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_templates_render_with_url_secret_and_prompt(set_env):
    set_env(PUBLIC_BASE_URL="https://example.ngrok.app/", TOOL_SECRET="s3cret")
    assert load_script().main() == 0
    tool = json.loads((ROOT / "build" / "submit_quote_tool.json").read_text())
    agent = json.loads((ROOT / "build" / "agent_supplier_r1.json").read_text())

    assert tool["value"]["url"] == "https://example.ngrok.app/tools/submit_quote"
    assert tool["value"]["headers"]["X-Dalaal-Token"] == "s3cret"
    assert tool["key"] == "custom_task" and not any(k.startswith("_") for k in tool)
    assert set(tool["value"]["param"]) == set(tool["parameters"]["properties"])  # names must match exactly

    cfg = agent["agent_config"]
    assert cfg["webhook_url"] == "https://example.ngrok.app/webhook/bolna"
    assert cfg["tasks"][0]["toolchain"]["pipelines"] == [["transcriber", "llm", "synthesizer"]]  # array of arrays
    prompt = agent["agent_prompts"]["task_1"]["system_prompt"]
    assert "submit_quote" in prompt and "{call_ref}" in prompt and "automated assistant" in prompt
    assert "{{" not in json.dumps(agent) and "{{" not in json.dumps(tool)


def test_render_refuses_without_public_url(set_env, capsys):
    set_env(PUBLIC_BASE_URL="")
    assert load_script().main() == 1


def test_all_five_agents_render_with_matching_variables(set_env):
    import re
    set_env(PUBLIC_BASE_URL="https://example.ngrok.app")
    assert load_script().main() == 0
    from app import orchestrator, orders, seed  # noqa: F401
    expected_vars = {  # what the orchestrator passes in user_data for each kind
        "supplier_r1": {"business_name", "items_spoken", "deadline_spoken", "call_ref", "competing_quote_spoken"},
        "supplier_r2": {"business_name", "items_spoken", "deadline_spoken", "call_ref", "counter_offer_spoken", "their_quote_spoken"},
        "approval": {"owner_name", "summary"},
        "confirm": {"business_name", "agreed_spoken", "delivery_time", "deadline_spoken"},
        "callback": {"owner_name", "message"},
        "intake": {"owner_name"},
    }
    for kind, allowed in expected_vars.items():
        cfg = json.loads((ROOT / "build" / f"agent_{kind}.json").read_text())
        text = cfg["agent_prompts"]["task_1"]["system_prompt"] + cfg["agent_config"]["agent_welcome_message"]
        used = set(re.findall(r"\{([a-z_0-9]+)\}", text))
        assert used <= allowed | {"call_ref"}, f"{kind} uses variables the code never sends: {used - allowed}"
        assert "automated assistant" in text


def test_round2_prompt_never_names_competitors_or_invents_prices():
    p = (ROOT / "bolna" / "prompts" / "supplier_round2.md").read_text()
    assert "Never say who the other supplier is" in p and "Never make up a price" in p


def test_sarvam_voice_has_the_language_bolna_requires():
    cfg = json.loads((ROOT / "bolna" / "supplier_agent.template.json").read_text())
    syn = cfg["agent_config"]["tasks"][0]["tools_config"]["synthesizer"]
    assert syn["provider"] == "sarvam" and syn["provider_config"]["language"] == "hi"  # not hi-IN


def test_phone_numbers_typed_with_spaces_are_glued_back():
    from app.seed import parse_number_args
    nums, errors = parse_number_args(["owner=+917975113319", "ramesh=+91", "93115", "09800", "gowda="])
    assert not errors and nums == {"owner": "+917975113319", "ramesh": "+919311509800", "gowda": ""}
    _, errors = parse_number_args(["ramesh=+91"])
    assert errors  # a bare country code is refused, never saved


def test_language_args_are_split_from_numbers():
    from app.seed import parse_language_args, parse_number_args
    langs, rest = parse_language_args(["kumar=+918983004130", "kumar.lang=KN", "ramesh.lang=en"])
    assert langs == {"kumar": "kn", "ramesh": "en"} and rest == ["kumar=+918983004130"]
    assert parse_number_args(rest) == ({"kumar": "+918983004130"}, [])
