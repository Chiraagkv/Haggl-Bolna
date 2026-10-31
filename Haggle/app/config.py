"""Settings, read from environment variables or a local .env file."""

import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Tests set DALAAL_IGNORE_ENV_FILE so a developer's real .env (key, tunnel URL, agent ids) never leaks in.
    model_config = SettingsConfigDict(env_file=None if os.environ.get("DALAAL_IGNORE_ENV_FILE") else ".env",
                                      env_file_encoding="utf-8", extra="ignore")

    # Bolna
    bolna_api_key: str = ""
    bolna_base_url: str = "https://api.bolna.ai"

    # Database
    database_url: str = "sqlite:///./dalaal.db"

    # Public URL that Bolna can reach (your tunnel)
    public_base_url: str = ""

    # Webhooks
    webhook_allowed_ips: str = "13.203.39.153,13.126.9.249,13.202.133.53"
    enforce_webhook_ips: bool = False

    # "bolna" places real calls. "fake" simulates suppliers from data/personas.json: no key, no cost.
    provider: str = "bolna"

    # Bolna agent ids (from scripts/create_agents.py or the dashboard)
    supplier_agent_id: str = ""        # round 1
    supplier_r2_agent_id: str = ""     # round 2 (falls back to the round-1 agent)
    approval_agent_id: str = ""
    confirm_agent_id: str = ""
    callback_agent_id: str = ""
    intake_agent_id: str = ""          # inbound; documented, not dialed by us

    # Shared secret the custom-function tool sends so strangers cannot post fake quotes.
    # Empty means "no check" (fine for the first local test, not for the demo).
    tool_secret: str = ""

    # Only these numbers may be dialed by our scripts (comma-separated E.164). Trial accounts
    # can only dial verified numbers anyway; this keeps real suppliers safe from test calls.
    verified_numbers: str = ""

    # Dialing rules
    require_verified_numbers: bool = True   # keep True until you deliberately call real suppliers
    # Bolna bills ~6 US cents/min (Rs 5.52) on preferred models and rounds telephony UP to the minute,
    # so a call capped at 60 s is one billed minute. Free tier: $5 once, about Rs 460.
    estimated_cost_per_call_inr: float = Field(default=6.0, ge=0)
    # Rupees per unit of `total_cost`. Measured on the first live call: total_cost 6.0 for 60 s and the
    # wallet fell 500 -> 494, so it is US cents: ~Rs 0.92 each (NOT 0.01).
    cost_unit_to_inr: float = 0.92
    # Rupees per unit of `wallet` from GET /user/me. Measured: the API says 500.0 when the dashboard shows
    # $5.00, so it is US cents: ~Rs 0.92 each.
    wallet_unit_to_inr: float = Field(default=0.92, ge=0)
    stage_timeout_seconds: int = Field(default=150, ge=10)  # round 2 / approval / booking / callback
    poll_stale_after_seconds: int = Field(default=45, ge=5)
    max_booking_attempts: int = Field(default=2, ge=1)
    max_quantity_per_item: float = Field(default=500.0, gt=0)  # sanity limit before booking

    # Ranking (Bible section 3) -- tunable assumptions, not measured facts
    lateness_cost_inr: float = 300.0
    late_prior_a: float = 1.0
    late_prior_b: float = 3.0
    credit_rate_per_month: float = 0.02
    split_min_saving_inr: float = 60.0
    treat_missing_delivery_time_as_ok: bool = False

    # Limits
    concurrency_limit: int = Field(default=2, ge=1)
    round1_deadline_seconds: int = Field(default=150, ge=10)  # PER WAVE: round 1 dials one wave per concurrency slot set
    cost_ceiling_per_order_inr: float = Field(default=75.0, ge=0)  # 4 suppliers + 2 round-2 + approval + confirms + callback
    daily_cap_inr: float = Field(default=400.0, ge=0)              # stays under the free tier's ~Rs 460
    kill_switch: bool = False
    retry_no_answer: bool = True          # one extra attempt for a round-1 supplier who did not pick up
    retry_min_seconds_left: int = 60      # ...only if the round-1 deadline is still this far away

    # Background loop (watchdog, dispatch, fake-provider delivery). Tests switch it off.
    background_loop: bool = True
    loop_interval_seconds: float = Field(default=2.0, ge=0.2)
    fake_delay_seconds: float = Field(default=2.0, ge=0)   # demo pacing for the fake provider
    owner_phone_override: str = ""                          # call this number instead of the owner's (testing)

    @property
    def allowed_ips(self) -> set[str]:
        return {ip.strip() for ip in self.webhook_allowed_ips.split(",") if ip.strip()}

    @property
    def verified_number_set(self) -> set[str]:
        return {n.strip() for n in self.verified_numbers.split(",") if n.strip()}

    @property
    def has_bolna_key(self) -> bool:
        return bool(self.bolna_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
