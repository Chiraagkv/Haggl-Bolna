# Bolna API gotchas (from Bolna's own AGENTS.md)

Paste this file, or Bolna's `https://www.bolna.ai/docs/AGENTS.md`, into your coding assistant's context.

| Thing | Fact |
| --- | --- |
| Base URL / auth | `https://api.bolna.ai`, header `Authorization: Bearer <key>`. Bad key → 401 "Access denied" |
| Create agent | `POST /v2/agent` returns **201** (not 200) with `{ agent_id, state }`. The field is `state`, not `status` |
| `toolchain.pipelines` | An **array of arrays**, e.g. `[["transcriber", "llm", "synthesizer"]]`. An array of strings is wrong |
| Make call | `POST /call` returns 200 with `{ execution_id, status: "queued" }`. `from_phone_number` is optional except for `trunk` agents |
| `scheduled_at` | Use a numeric offset like `+00:00`, **never `Z`** (500). At least 2 minutes ahead (else 400). Rounded up to the next 10-minute mark |
| Get execution | `GET /executions/{id}`. Fields include `status`, `conversation_duration`, `total_cost`, `recording_url`, `extracted_data` |
| Lifecycle | `queued → initiated → ringing → in-progress → call-disconnected → completed` (or `no-answer` / `busy` / `failed`) |
| Terminal statuses | `completed`, `no-answer`, `busy`, `failed`, `canceled`, `stopped`, `error`, `balance-low` |
| **Wait for `completed`** | At `call-disconnected` the duration, cost, recording and extracted data are still null or 0. They arrive a few seconds later with `completed` |
| Batches | `POST /batches` is multipart (`agent_id` + CSV `file`) and returns **201** `{ batch_id, state }`. `GET /batches/{id}/executions` returns a **bare array** |
| Webhook source IPs | `13.203.39.153`, `13.126.9.249`, `13.202.133.53`. Allowlist all three or events are dropped |
| Account info | `GET /user/me` returns `{ id, name, email, wallet, concurrency }` — used by `scripts/check_setup.py` |
| **Live `/user/me` (seen 2026-10-27)** | `concurrency` is an object `{"max": 2, "current": 0}`, not a number; `wallet` is **US cents** (`500.0` = $5.00) |
| **Sarvam voice (seen 2026-10-27)** | `synthesizer.provider_config` needs `language` (plain `hi`, never `hi-IN`). `bulbul:v2` voices such as `anushka` are gone; `bulbul:v3` voices: `kavya`, `priya`, `ritu`, `simran`, `pooja`, … |
| **No dashboard needed (seen 2026-10-30)** | A custom function goes in `tools_config.api_tools` as `{"tools": [{name, description, pre_call_message, parameters, key: "custom_task"}], "tools_params": {name: {method, url, api_token, param: "<JSON string>", headers}}}`; stored as sent, headers included. Extractions: `POST /dispositions/bulk {agent_id, dispositions: [{name, question, category, is_subjective: true, subjective_type: "text"}]}` → 201 |
| **Dispositions on an agent** | `GET /v2/agent/{id}` lists `dispositions` as bare **ids**, not names (plus some Bolna-owned ones). Match names through `GET /dispositions/` → `user_owned`, or every re-run duplicates them |
| **Updating an agent** | `PATCH` changes prompts/welcome/webhook only. `PUT /v2/agent/{id}` with the create body replaces the whole config (tools, `call_terminate`) and keeps linked dispositions |
| **Hang-ups (seen 2026-10-30)** | A call the callee hangs up still ends `completed`, with extractions. Why it ended is in `termination_reason` (`user_hung_up`, `inactivity_timeout` after 10 s silence, `max_duration_reached`) and `telephony_data.hangup_by` / `hangup_reason` |
| **Multilingual (accepted 2026-10-30)** | `tools_config.multilingual_config = {enabled, active_language, language_switch_trigger, languages: {code: {transcriber: {language}, synthesizer: {provider, provider_config}, system_prompt, welcome_message}}}`, at least 2 languages, plain codes (`kn`, not `kn-IN`). Needs PUT (PATCH ignores tools_config). Start a call in a language with `user_data.agent_language` (or `agent_data.language`, never both: 400) |
| **Extractor ignores "Return ONLY JSON"** | Seen live: `confirmed` came back as a sentence ("Yes, the supplier confirmed …"). Ask one-word / one-number questions and read them leniently (`services.yes_no`, `services.number`) |
| Trial limits | 2 concurrent calls, verified numbers only (OTP, dashboard → User Profile → Verified Numbers). Paid starts at 10. Over-limit calls are queued, not rejected |
| Free credit | $5 once on signup, about 80 minutes. ~6¢/min (Rs 5.52) on preferred models; telephony rounds **up to the minute**, so every agent is capped at 60 s (intake 90 s) |
| Caller ID | Omit `from_phone_number` to use Bolna's shared numbers (works on trial). Inbound needs a bought number, so we use outbound intake |

Not documented on that page (check Bolna's OpenAPI spec or guides before relying on it): the exact `POST /call` body fields (`agent_id`, `recipient_phone_number`, `user_data`), the webhook payload schema, the custom function tool shape, and the extraction schema.
