import os
import sys
from pathlib import Path

# Make `app` importable and force a throwaway database for tests.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DALAAL_IGNORE_ENV_FILE"] = "1"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["BOLNA_API_KEY"] = ""
os.environ["TOOL_SECRET"] = ""
os.environ["ENFORCE_WEBHOOK_IPS"] = "false"
os.environ["BACKGROUND_LOOP"] = "false"
os.environ["PROVIDER"] = "fake"
os.environ["FAKE_DELAY_SECONDS"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.config import get_settings  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    """Every test gets an empty database and fresh settings."""
    get_settings.cache_clear()
    db.reset_engine()
    db.init_db()
    from app import providers
    providers.set_provider(None)
    yield
    providers.set_provider(None)
    db.reset_engine()
    get_settings.cache_clear()


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app)


@pytest.fixture
def session():
    gen = db.get_session()
    s = next(gen)
    yield s
    s.close()


@pytest.fixture
def set_env(monkeypatch):
    """Change a setting for one test."""

    def _set(**kv):
        for k, v in kv.items():
            monkeypatch.setenv(k, str(v))
        get_settings.cache_clear()

    return _set


@pytest.fixture
def fake():
    from app import providers
    f = providers.FakeProvider(delay=0)
    providers.set_provider(f)
    return f


@pytest.fixture
def world(session, fake):
    """Seeded demo owner + suppliers, and the demo order spec."""
    from app import seed
    owner = seed.ensure_demo_data(session)
    return owner
