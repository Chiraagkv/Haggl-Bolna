"""Thin Bolna API client, written against Bolna's AGENTS.md (see docs/BOLNA_GOTCHAS.md).

The status-code checks are deliberate: Bolna returns 201 (not 200) for create-agent and
create-batch, and 200 for POST /call.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import get_settings


class BolnaError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def format_scheduled_at(minutes_ahead: int = 3, now: datetime | None = None) -> str:
    """ISO timestamp for `scheduled_at`.

    Bolna rejects a trailing `Z` with a 500 and wants a numeric offset, at least 2 minutes in
    the future (and rounds up to the next 10-minute mark).
    """
    if minutes_ahead < 2:
        raise ValueError("scheduled_at must be at least 2 minutes ahead")
    when = (now or datetime.now(timezone.utc)) + timedelta(minutes=minutes_ahead)
    return when.replace(microsecond=0).isoformat()  # '+00:00', never 'Z'


class BolnaClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 transport: httpx.BaseTransport | None = None):
        s = get_settings()
        key = api_key if api_key is not None else s.bolna_api_key
        if not key:
            raise BolnaError("BOLNA_API_KEY is not set")
        self._http = httpx.Client(
            base_url=base_url or s.bolna_base_url,
            headers={"Authorization": f"Bearer {key}"},
            timeout=30.0,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def _expect(self, resp: httpx.Response, ok: int | tuple[int, ...]) -> dict:
        try:
            body = resp.json()
        except ValueError:
            body = resp.text
        if resp.status_code == 401:
            raise BolnaError("Bolna rejected the API key (401)", 401, body)
        if resp.status_code not in (ok if isinstance(ok, tuple) else (ok,)):
            raise BolnaError(f"Bolna returned {resp.status_code}, expected {ok}: {body}", resp.status_code, body)
        return body if isinstance(body, dict) else {"body": body}

    # -- agents ---------------------------------------------------------------
    def create_agent(self, config: dict) -> dict:
        """POST /v2/agent -> 201 {agent_id, state}. (200 would be wrong: that is the v1 endpoint.)"""
        body = self._expect(self._http.post("/v2/agent", json=config), 201)
        if "agent_id" not in body:
            raise BolnaError(f"no agent_id in response: {body}", 201, body)
        return body

    def get_agent(self, agent_id: str) -> dict:
        """GET /v2/agent/{id} -> the agent, including `tasks` and its linked `dispositions`."""
        return self._expect(self._http.get(f"/v2/agent/{agent_id}"), 200)

    def update_agent(self, agent_id: str, config: dict) -> dict:
        """PUT /v2/agent/{id} with the same body as create -> 200 {agent_id, status: 'updated'}.
        Replaces the whole config (tools included)."""
        return self._expect(self._http.put(f"/v2/agent/{agent_id}", json=config), 200)

    def create_dispositions(self, agent_id: str, items: list[dict]) -> dict:
        """POST /dispositions/bulk -> 201 {message, ids}. Creates extractions and links them to the agent."""
        return self._expect(self._http.post("/dispositions/bulk", json={"agent_id": agent_id, "dispositions": items}), 201)

    def list_dispositions(self) -> list[dict]:
        """GET /dispositions/ -> {user_owned: [...], organization_owned: [...]}; the account's own extractions."""
        body = self._expect(self._http.get("/dispositions/"), 200)
        return list(body.get("user_owned") or []) + list(body.get("organization_owned") or [])

    def delete_disposition(self, disposition_id: str) -> None:
        self._expect(self._http.delete(f"/dispositions/{disposition_id}"), (200, 204))

    def patch_agent(self, agent_id: str, body: dict) -> dict:
        """PATCH /v2/agent/{id} -> 200 {message, state: 'updated'}. Only prompts, welcome message, webhook
        URL, voice and a few other agent_config fields can change this way; everything left out (and the
        tools and extractions attached in the dashboard) stays as saved."""
        return self._expect(self._http.patch(f"/v2/agent/{agent_id}", json=body), 200)

    # -- calls ----------------------------------------------------------------
    def make_call(
        self,
        agent_id: str,
        recipient_phone_number: str,
        user_data: dict | None = None,
        from_phone_number: str | None = None,
        scheduled_at: str | None = None,
        retry_config: dict | None = None,
    ) -> dict:
        """POST /call -> 200 {message, status: 'queued', execution_id}."""
        payload: dict[str, Any] = {"agent_id": agent_id, "recipient_phone_number": recipient_phone_number}
        if user_data:
            payload["user_data"] = user_data
        if from_phone_number:
            payload["from_phone_number"] = from_phone_number
        if scheduled_at:
            payload["scheduled_at"] = scheduled_at
        if retry_config:
            payload["retry_config"] = retry_config
        body = self._expect(self._http.post("/call", json=payload), 200)
        if "execution_id" not in body:
            raise BolnaError(f"no execution_id in response: {body}", 200, body)
        return body

    def get_execution(self, execution_id: str) -> dict:
        """GET /executions/{id}. Read duration/cost/extraction only once status is terminal."""
        return self._expect(self._http.get(f"/executions/{execution_id}"), 200)

    def account(self) -> dict:
        """GET /user/me -> {id, name, email, wallet, concurrency}."""
        return self._expect(self._http.get("/user/me"), 200)
