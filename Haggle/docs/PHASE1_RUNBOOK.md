# Phase 1 runbook — proving the Bolna loop with real calls

Tickets #7, #10, #11, #13, #14. The code for these is written and tested **offline**. What it
cannot prove is how Bolna really behaves, and that needs a key, a number and a teammate with a
phone. Do these in order. Every call costs wallet money, so keep a teammate ready before you dial.

## Before the first call

1. `.env` has `BOLNA_API_KEY`, `PUBLIC_BASE_URL` (your tunnel), `TOOL_SECRET` (any random string),
   `VERIFIED_NUMBERS` (your teammates, E.164, comma-separated).
2. Server running (`uvicorn app.main:app --port 8000`) and the tunnel up. `curl <PUBLIC_BASE_URL>/health` works from outside.
3. Rehearse for free first: `python scripts/simulate_call.py` and look at `/debug/calls`. If that
   shows oil = 62 (confirmed), the server side is healthy.
4. `python scripts/check_setup.py`; paste the output in `NOTES.md`.

## #7 — First agent and first call

```bash
python scripts/render_bolna_files.py
python scripts/create_agents.py                  # expects 201 + agent_id for each of the 5 agents
```

- If Bolna rejects the config, read its message. The **synthesizer block** and the transcriber
  extras in `bolna/supplier_agent.template.json` are guesses. Fix and retry, or create the agent in
  the dashboard and set `SUPPLIER_AGENT_ID` yourself.
- Put the returned id in `.env` as `SUPPLIER_AGENT_ID`.

```bash
python scripts/place_test_call.py --to +91XXXXXXXXXX --wait
```

**Pass:** the teammate's phone rings, they hear the opening line (it says it is an automated
assistant), and `/debug/events` shows webhooks arriving.
**Record in NOTES.md:** did the welcome message fill `{business_name}`? Did the prompt variables
(`items_spoken`, `deadline_spoken`, `call_ref`) fill in?

## #10 — The real webhook, and the extraction at `completed`

1. In the dashboard, add the `quotes_json` extraction exactly as described in
   `bolna/extraction_quotes_json.md`, and check the agent's webhook URL (Extractions tab).
2. Call again. The teammate says a price: "pyaaz pachchis rupaye kilo".
3. Open `/debug/events`. **The first real `completed` payload is the ground truth.** Compare it with
   what `quotes_from_extracted_data` in `app/services.py` expects:
   `extracted_data -> <category> -> quotes_json -> subjective` holding a JSON list.
4. Open `/debug/calls`. There should be a quote with `provisional: false`, `source: extraction`.

**Pass:** a stored, structured quote with no manual steps.
**If the shape differs:** only `quotes_from_extracted_data` needs changing; nothing else.

## #11 — Does `submit_quote` fire mid-call, and does the call carry on?

1. Add the tool in the dashboard from `build/submit_quote_tool.json` (Tools tab, custom function).
2. Call again, say a price, and **watch `/debug/calls` while still on the call**.

**Pass:** the quote appears with `provisional: true` *before* hanging up, and the conversation
continues afterwards. Then at `completed` it flips to `provisional: false`.
**Record in NOTES.md (the day-1 table):** yes/no. If no, the fallback is to update the dashboard at
`completed` only; the demo still works, just less instantly.
**Things to check if it never fires:**
- the tool's `description` (it drives when the LLM calls it),
- that the parameter names match between `properties` and `param` (case-sensitive),
- whether Bolna sends the arguments as JSON (POST) or a query string (GET): the server accepts both,
- that `X-Dalaal-Token` matches `TOOL_SECRET`, and Bolna's IPs are not blocked.

## #13 — Transcriber tuning

The template already sets `saaras:v4` (the only Sarvam model that reads `keywords`). In the
dashboard add up to 50 keywords of at most 64 characters: item names, units, number words, supplier
names (`pyaaz, tel, kilo, quintal, litre, pachchis, chhabbis, ...`). Place the same scripted price
10 times before and after and compare what `/debug/events` shows in the transcript.

**Pass:** price and unit words transcribe better than before, counted over at least 10 utterances.

## #14 — The round-1 prompt in three languages

`bolna/prompts/supplier_round1.md` is the Bible's Appendix C prompt. Run three scripted calls per
language (Hindi, English; Kannada if you can). Check each yields the right quote, the disclosure is
spoken, and a "don't call me again" ends the call politely. For Kannada, create a second agent from
the template with `"language": "kn"` and a Kannada welcome message.

## Known untested (as of writing)

| What | Why it matters | Where to fix |
| --- | --- | --- |
| `POST /v2/agent` body (synthesizer, `webhook_url`) | Agent creation may be rejected | `bolna/supplier_agent.template.json` |
| How the tool is attached to the agent | Not documented on the pages read | Dashboard, Tools tab |
| Extraction payload shape | Quotes would not be stored | `quotes_from_extracted_data` |
| Tool arguments: JSON vs query string | The tool call could be rejected | Server accepts both already |
| `call_ref` reaching the tool | Quotes could not be joined to calls | Prompt line "Always pass call_ref ..." |
| `total_cost` units | The schema says cents, the example looks like rupees | Check against a real call before the cost ceiling (#18) |

Everything else (idempotent webhooks, status ordering, provisional-to-confirmed quotes, the number
parser, the safety guards) is covered by the automated tests.
