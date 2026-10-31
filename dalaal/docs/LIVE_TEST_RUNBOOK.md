# Live test runbook — proving Dalaal against real Bolna

Everything here was built and tested against a fake provider. This is the order in which to find out
what real Bolna does differently, cheapest and least risky first. Stop at the first surprise and write
it in `NOTES.md`; the raw payloads are always in `GET /debug/events`.

Before anything: `.env` has `BOLNA_API_KEY`, `PUBLIC_BASE_URL` (tunnel), `TOOL_SECRET`, `VERIFIED_NUMBERS`
(teammates only, also verified in Bolna on a trial account). Keep `PROVIDER=bolna`.

## Step 0 — plumbing (10 min, free)
1. `python scripts/check_setup.py` → note concurrency and wallet in `NOTES.md`.
2. `uvicorn app.main:app --port 8000`, `bash scripts/tunnel.sh`, then `curl https://<url>/health` from your phone's data.

## Step 1 — create the agents (5 min)
1. `python scripts/render_bolna_files.py && python scripts/create_agents.py`
2. If Bolna refuses a config, its exact error is printed. The `synthesizer` block in
   `bolna/supplier_agent.template.json` is the most likely cause; or build the agent in the dashboard and copy its id.
3. Put the printed `*_AGENT_ID` lines in `.env`. Restart the server.
4. In the dashboard: attach the `submit_quote` tool (from `build/submit_quote_tool.json`) to the **two supplier agents**,
   and create the extractions in `bolna/extractions.md` (set the webhook URL on the agent).

## Step 2 — one supplier call (the Phase 1 proof; tickets #10, #11, #13, #14)
1. `python scripts/seed_demo.py owner=+91… kumar=+91… ramesh=+91… gowda=+91… lakshmi=+91…` (teammates' verified numbers).
2. `python scripts/place_test_call.py` (round-1 agent to ONE teammate). Teammate plays Kumar: "pyaaz pachchis rupaye kilo, tel saath rupaye litre."
3. Check `GET /debug/calls`: a **provisional** quote while talking (proves `submit_quote` fires mid-call, #11) and a
   **confirmed** one after `completed` (proves the extraction path, #10).
4. Look at `GET /debug/events`: write down the real `extracted_data` shape, whether tool arguments came as JSON or a query
   string, and whether `call_ref` arrived. If `extraction_value` / `quotes_from_extracted_data` need adjusting, those are the only two functions.
5. Cost: compare `cost` on the call with the Bolna wallet movement; set `COST_UNIT_TO_INR` (if it is US cents, ~0.92 — not 0.01).

## Step 3 — a whole order with 2 teammates (rounds 1–2, approval, booking, callback)
1. Order via `POST /api/orders` or the dashboard: open `http://localhost:8000`. (Type the items, check which pairs it will call, then **Start calling**; in live mode it asks before dialing.)
   ```bash
   curl -XPOST localhost:8000/api/orders -H 'content-type: application/json' \
     -d '{"items":[{"name":"onions","quantity":20,"unit":"kg"},{"name":"oil","quantity":10,"unit":"litre"}],"deadline":"07:00","budget":1200}'
   ```
2. With only two verified teammates, suppliers without a number are skipped (selection requires a phone) — set
   `kumar` and `ramesh` to the two numbers and the others to nothing, or accept that unlisted suppliers are skipped.
3. Watch the board. Teammates should (a) quote different prices, (b) in round 2 hear "mujhe kahin aur se … ka bhaav mil raha hai"
   and drop their price (c) say "haan" on the approval call (set `--budget` low to force it) (d) confirm the order.

## Step 4 — try to break it (on purpose)
Have a teammate: not answer; hang up mid-quote; say "nahi chahiye, dobara call mat karna" (→ `do_not_call`);
give a price in "petti"; change the quantity on the confirm call; say "no" on the approval call. Each should end in a
clean state, never a booking you did not approve. The fake provider already proves the logic: `pytest tests/test_e2e.py`.

## Open questions this run answers (write answers in NOTES.md)
| # | Question | Where to look |
|---|---|---|
| 1 | Does `submit_quote` fire mid-call, and does the call continue? | `/debug/calls` provisional quote during the call |
| 2 | Real `extracted_data` shape? | `/debug/events`, the `completed` webhook |
| 3 | Do per-call variables (`call_ref`, `counter_offer_spoken`) reach the prompt? | transcript says the right numbers |
| 4 | Is `total_cost` cents? | wallet before/after |
| 5 | Does the trial caller-ID/registration allow supplier calls? | ask Bolna in the builder Slack; write the answer |
| 6 | Does `saaras:v4` keyword biasing help prices? | compare 5 calls with/without |

## Cost guard-rails already in code
`COST_CEILING_PER_ORDER_INR` (75), `DAILY_CAP_INR` (400), `KILL_SWITCH=true`, one live order per owner, and the
dashboard's "Stop order" button. A failed dial never retries in a loop.
