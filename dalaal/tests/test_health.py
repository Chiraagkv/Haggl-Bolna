from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["kill_switch"] is False
    assert body["bolna_key_set"] is False  # tests run without a key


def test_config_check_exposes_limits_but_no_secrets():
    r = client.get("/config-check")
    assert r.status_code == 200
    body = r.json()
    assert body["concurrency_limit"] >= 1
    assert "13.203.39.153" in body["allowed_webhook_ips"]
    assert not any("key" in k.lower() for k in body)
