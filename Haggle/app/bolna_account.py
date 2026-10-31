"""Read the account's real limits from Bolna (ticket #1).

GET /user/me returns { id, name, email, wallet, concurrency } per Bolna's AGENTS.md. Live, `concurrency`
is an object {"max": 2, "current": 0} and `wallet` is in US cents (500.0 = $5.00); a bare number is
still accepted in case the docs' shape comes back.
"""

from dataclasses import dataclass

import httpx

# Round 1 dials suppliers in pairs that sell the same items (orchestrator.plan_round1_waves), so the
# trial account's two concurrent calls are enough. More concurrency just means bigger waves.
NEEDED_CONCURRENCY = 2


@dataclass
class AccountInfo:
    name: str
    email: str
    wallet: float | None
    concurrency: int | None

    @property
    def can_run_pairs(self) -> bool:
        return self.concurrency is not None and self.concurrency >= NEEDED_CONCURRENCY


def fetch_account(client: httpx.Client) -> AccountInfo:
    """Call GET /user/me with an already-authenticated client."""
    resp = client.get("/user/me")
    if resp.status_code == 401:
        raise PermissionError("Bolna rejected the API key (401 Access denied).")
    resp.raise_for_status()
    data = resp.json()
    wallet = data.get("wallet")
    concurrency = data.get("concurrency")
    if isinstance(concurrency, dict):
        concurrency = concurrency.get("max")
    return AccountInfo(
        name=str(data.get("name") or ""),
        email=str(data.get("email") or ""),
        wallet=float(wallet) if wallet is not None else None,
        concurrency=int(concurrency) if concurrency is not None else None,
    )


def make_client(api_key: str, base_url: str, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        base_url=base_url,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=20.0,
        transport=transport,
    )


def notes_snippet(info: AccountInfo, read_on: str) -> str:
    """Markdown block to paste into NOTES.md."""
    verdict = (
        "OK: round 1 can call suppliers in pairs."
        if info.can_run_pairs
        else "NOT ENOUGH: round 1 needs two calls at once (one pair of suppliers)."
    )
    return (
        f"- Read on: {read_on}\n"
        f"- Account: {info.name} <{info.email}>\n"
        f"- Concurrency limit: {info.concurrency}\n"
        f"- Wallet balance (raw, set WALLET_UNIT_TO_INR from it): {info.wallet}\n"
        f"- Verdict: {verdict}\n"
    )
