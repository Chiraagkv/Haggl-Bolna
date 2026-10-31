"""FastAPI entry point.

Phase 0: /health and /config-check.
Phase 1: /webhook/bolna, /tools/submit_quote, /debug/*.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.config import get_settings
from app.db import db_ok, init_db
from app.api import router as api_router
from app.routes import router


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()  # creates tables in dev; real migrations arrive with ticket #15
    task = asyncio.create_task(_loop()) if get_settings().background_loop else None
    yield
    if task:
        task.cancel()


def _one_pass() -> None:
    from app import orchestrator, providers
    from app.db import get_session

    session = next(get_session())
    try:
        provider = providers.get_provider()
        provider.pump(session)
        orchestrator.tick(session, provider)
    finally:
        session.close()


async def _loop() -> None:
    """Watchdog + dispatcher + fake-provider delivery. Errors never stop it."""
    log = logging.getLogger("dalaal.loop")
    while True:
        try:
            await asyncio.to_thread(_one_pass)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("background pass failed")
        await asyncio.sleep(get_settings().loop_interval_seconds)


app = FastAPI(title="Dalaal", version=__version__, lifespan=lifespan)
app.include_router(router)
app.include_router(api_router)


@app.get("/health")
def health() -> dict:
    """Liveness check. Hit this through your public tunnel to prove Bolna can reach you."""
    s = get_settings()
    return {
        "status": "ok",
        "version": __version__,
        "database": "ok" if db_ok() else "unreachable",
        "bolna_key_set": s.has_bolna_key,
        "public_base_url_set": bool(s.public_base_url),
        "tool_secret_set": bool(s.tool_secret),
        "kill_switch": s.kill_switch,
        "provider": s.provider,
    }


@app.get("/config-check")
def config_check() -> dict:
    """Non-secret view of the limits the app is running with."""
    s = get_settings()
    return {
        "concurrency_limit": s.concurrency_limit,
        "round1_deadline_seconds": s.round1_deadline_seconds,
        "cost_ceiling_per_order_inr": s.cost_ceiling_per_order_inr,
        "daily_cap_inr": s.daily_cap_inr,
        "enforce_webhook_ips": s.enforce_webhook_ips,
        "allowed_webhook_ips": sorted(s.allowed_ips),
    }
