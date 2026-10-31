"""app/bolna_setup.py: the API replaces every dashboard step. No network: a fake Bolna answers."""

import json

import httpx

from app import bolna_setup
from app.bolna_client import BolnaClient
from app.config import Settings


def settings(**kw):
    base = dict(public_base_url="https://abc.trycloudflare.com", tool_secret="s3cret")
    return Settings(_env_file=None, **(base | kw))


def test_supplier_agents_carry_the_tool_with_the_current_url_and_secret():
    agents = bolna_setup.render_agents(settings())
    for kind, cfg in agents.items():
        tools = cfg["agent_config"]["tasks"][0]["tools_config"].get("api_tools")
        assert cfg["agent_config"]["webhook_url"] == "https://abc.trycloudflare.com/webhook/bolna"
        if kind in ("supplier_r1", "supplier_r2"):
            [fn] = tools["tools"]
            p = tools["tools_params"]["submit_quote"]
            assert fn["key"] == "custom_task" and fn["name"] == "submit_quote"
            assert p["url"] == "https://abc.trycloudflare.com/tools/submit_quote" and p["headers"]["X-Dalaal-Token"] == "s3cret"
            assert json.loads(p["param"])["call_ref"] == "%(call_ref)s"
        else:
            assert tools is None


class FakeBolna:
    """Just enough of the Bolna API for sync_agents."""

    def __init__(self, agents=None, dispositions=None):
        self.agents = agents or {}            # id -> {"dispositions": [ids]}
        self.dispositions = dispositions or []  # [{id, name, question, created_at}]
        self.calls = []
        self.n = 0

    def handler(self, req: httpx.Request) -> httpx.Response:
        path, m = req.url.path, req.method
        self.calls.append((m, path))
        body = json.loads(req.content) if req.content else None
        if m == "POST" and path == "/v2/agent":
            self.n += 1
            aid = f"new-{self.n}"
            self.agents[aid] = {"dispositions": []}
            return httpx.Response(201, json={"agent_id": aid, "state": "created"})
        if path.startswith("/v2/agent/"):
            aid = path.rsplit("/", 1)[1]
            if aid not in self.agents:
                return httpx.Response(404, json={"message": "not found"})
            if m == "GET":
                return httpx.Response(200, json={"id": aid, **self.agents[aid]})
            if m == "PUT":
                return httpx.Response(200, json={"agent_id": aid, "status": "updated"})
        if m == "GET" and path == "/dispositions/":
            return httpx.Response(200, json={"user_owned": self.dispositions, "organization_owned": []})
        if m == "POST" and path == "/dispositions/bulk":
            ids = []
            for item in body["dispositions"]:
                self.n += 1
                d = {"id": f"d{self.n}", "name": item["name"], "question": item["question"], "created_at": f"{self.n:04d}"}
                self.dispositions.append(d)
                self.agents[body["agent_id"]]["dispositions"].append(d["id"])
                ids.append(d["id"])
            return httpx.Response(201, json={"message": "ok", "ids": ids})
        if m == "DELETE" and path.startswith("/dispositions/"):
            did = path.rsplit("/", 1)[1]
            self.dispositions = [d for d in self.dispositions if d["id"] != did]
            for a in self.agents.values():
                a["dispositions"] = [x for x in a["dispositions"] if x != did]
            return httpx.Response(200, json={})
        return httpx.Response(500, json={"unexpected": f"{m} {path}"})


def client_for(fake):
    return BolnaClient(api_key="k", base_url="https://api.bolna.ai", transport=httpx.MockTransport(fake.handler))


def test_first_run_creates_everything_and_second_run_only_updates():
    fake = FakeBolna()
    ids, failed = bolna_setup.sync_agents(client_for(fake), settings(), log=lambda _: None)
    assert failed == 0 and len(ids) == 6 and all(v.startswith("new-") for v in ids.values())
    spec = bolna_setup.load_extractions()
    assert sorted(d["name"] for d in fake.dispositions) == sorted(n for ns in spec["by_kind"].values() for n in ns)
    agent_env = {bolna_setup.ENV_NAME[k].lower(): v for k, v in ids.items()}
    fake.calls.clear()
    ids2, failed = bolna_setup.sync_agents(client_for(fake), settings(**agent_env), log=lambda _: None)
    assert ids2 == ids and failed == 0
    assert not any(m == "POST" for m, _ in fake.calls)  # nothing new created
    assert sum(1 for m, _ in fake.calls if m == "PUT") == 6  # the new tunnel URL reaches every agent


def test_duplicates_and_stale_questions_are_fixed_and_unknown_ones_left_alone():
    q = bolna_setup.load_extractions()["questions"]
    disp = [{"id": "a", "name": "quotes_json", "question": q["quotes_json"], "created_at": "1"},
            {"id": "b", "name": "quotes_json", "question": q["quotes_json"], "created_at": "2"},
            {"id": "c", "name": "do_not_call", "question": "old wording", "created_at": "3"}]
    fake = FakeBolna(agents={"r1": {"dispositions": ["a", "b", "c", "bolna-builtin"]}}, dispositions=disp)
    made = bolna_setup.ensure_extractions(client_for(fake), "r1", "supplier_r1")
    assert made == ["do_not_call"]
    linked = fake.agents["r1"]["dispositions"]
    assert "a" in linked and "b" not in linked and "c" not in linked and "bolna-builtin" in linked
    assert sorted(d["name"] for d in fake.dispositions) == ["do_not_call", "quotes_json"]


def test_deleted_agent_is_recreated():
    fake = FakeBolna()
    ids, _ = bolna_setup.sync_agents(client_for(fake), settings(supplier_agent_id="gone"), log=lambda _: None)
    assert ids["supplier_r1"].startswith("new-")


def test_cloudflared_url_is_read_from_its_log():
    from scripts.start import parse_cloudflare_url
    line = "2026-10-30T10:00:00Z INF |  https://instant-modular-productions-pay.trycloudflare.com                     |"
    assert parse_cloudflare_url(line) == "https://instant-modular-productions-pay.trycloudflare.com"
    assert parse_cloudflare_url("INF Requesting new quick Tunnel on trycloudflare.com...") is None


def test_every_agent_speaks_hindi_english_and_kannada():
    for kind, cfg in bolna_setup.render_agents(settings()).items():
        ml = cfg["agent_config"]["tasks"][0]["tools_config"]["multilingual_config"]
        assert ml["enabled"] and ml["active_language"] == "hi" and set(ml["languages"]) == {"hi", "en", "kn"}
        for code, entry in ml["languages"].items():
            assert entry["transcriber"]["language"] == code  # plain codes: Sarvam rejects hi-IN / kn-IN
            assert entry["synthesizer"]["provider_config"]["language"] == code
            assert entry["welcome_message"] and "{{" not in entry["system_prompt"]
        assert "ನಮಸ್ಕಾರ" in ml["languages"]["kn"]["welcome_message"]
        assert "switch to" not in cfg["agent_prompts"]["task_1"]["system_prompt"]  # Bolna switches, not the prompt


def test_calls_start_in_the_persons_language(session, world, fake):
    from app import orchestrator as orc, seed
    spec = seed.demo_order_spec()
    o = orc.create_order(session, world.id, spec["items"], spec["deadline"], spec["budget"])
    orc.run_until_idle(session, fake) if orc.start_order(session, o.id) else None
    langs = {(c.kind, c.user_data.get("supplier_key")): c.user_data["agent_language"] for c in fake.placed}
    assert langs[("supplier_r1", "gowda")] == "kn" and langs[("supplier_r1", "kumar")] == "hi"
    assert langs[("callback", "")] == "hi"
    assert bolna_setup.call_language("ta") == "hi" and bolna_setup.call_language("EN") == "en"
