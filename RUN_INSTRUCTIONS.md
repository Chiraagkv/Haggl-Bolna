# Running Dalaal, start to finish

## A. Offline first (no key, about 5 minutes)
Do this first so you know the code runs on your machine.
```bash
unzip dalaal-complete.zip && cd dalaal
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m pytest -q                                    # expect all green, about 190 tests
python scripts/run_demo.py                             # prints a whole order in the terminal
PROVIDER=fake FAKE_DELAY_SECONDS=1.5 uvicorn app.main:app --port 8000
```
Open http://localhost:8000, check the pre-filled order and click **Start calling**. On Windows, set the variables first with `set PROVIDER=fake` and `set FAKE_DELAY_SECONDS=1.5`, then run `uvicorn`.

## B. Bolna account setup (your tasks, once)
1. Create the Bolna account and API key. Ask in the Bolna builder Slack for sponsor credits or the paid plan, because trial accounts allow only 2 concurrent calls.
2. Calling number: on the free tier, leave `from_phone_number` out and Bolna uses its shared numbers. Buying one costs money and is only needed for inbound.
3. Verify 3-5 teammates' phone numbers in Bolna. On a trial you can only dial verified numbers. These teammates play Kumar, Ramesh, Gowda and the owner.

## C. Go live
```bash
cp .env.example .env
# edit .env: BOLNA_API_KEY=...   PROVIDER=bolna
bash scripts/tunnel.sh                    # needs ngrok or cloudflared; copy the https URL
# edit .env: PUBLIC_BASE_URL=https://your-url
python scripts/go_live.py owner=+91XXXXXXXXXX kumar=+91XXXXXXXXXX ramesh=+91XXXXXXXXXX gowda=+91XXXXXXXXXX lakshmi=+91XXXXXXXXXX
```
`go_live.py` writes `VERIFIED_NUMBERS` and `TOOL_SECRET` into `.env`, seeds your numbers, renders the Bolna files,
creates the agents (writing their ids into `.env`) and prints a checklist. Fix anything marked **XX** and run it again;
existing agent ids are never replaced. If Bolna rejects an agent config, the exact error is printed. The `synthesizer`
block in `bolna/supplier_agent.template.json` is the likeliest cause; you can also build that agent in the Bolna
dashboard and paste its id into `.env`.

## D. Two things only the Bolna dashboard can do
1. Attach the `submit_quote` tool to the round-1 and round-2 supplier agents (template: `build/submit_quote_tool.json`).
2. Create the extractions in `bolna/extractions.md` on each agent: `quotes_json`, `do_not_call`, `approval`, `confirmed`, `order_json`.

## E. Start the server and prove it, in this order
```bash
uvicorn app.main:app --port 8000          # second terminal; keep the tunnel running
curl https://<your-url>/health            # from your phone's data: proves Bolna can reach you
curl localhost:8000/api/preflight         # "ready": true
```
1. **One call:** `python scripts/place_test_call.py`. A teammate says "pyaaz pachchis rupaye kilo". Open `/debug/calls`:
   a provisional quote appears during the call, a confirmed one after it ends. `/debug/events` shows Bolna's real
   payloads; note them in `NOTES.md`.
2. **Whole order:** open http://localhost:8000, or:
   ```bash
   curl -XPOST localhost:8000/api/orders -H 'content-type: application/json' \
     -d '{"items":[{"name":"onions","quantity":20,"unit":"kg"},{"name":"oil","quantity":10,"unit":"litre"}],"deadline":"07:00","budget":1200}'
   ```
   Teammates quote different prices. In round 2 they hear a real competing price and drop theirs. Use `"budget":1000`
   to force the owner approval call. The owner says yes, the booking is confirmed, the owner gets the callback.
3. **Voice intake (optional):** `curl -XPOST localhost:8000/api/intake/call`. The owner speaks an order and it starts by
   itself. Needs the intake agent and its `order_json` extraction.
4. **Break it on purpose:** teammates do not answer, hang up, say "dobara call mat karna", or change the quantity on the confirm call.
5. **Numbers for the pitch:** `python scripts/metrics.py`.

## F. If something goes wrong
- **Stop everything:** the dashboard's **Stop order** button, or `KILL_SWITCH=true` and restart.
- **No quote appears:** check `/debug/events`. If the `extracted_data` shape differs from what the code expects, adjust
  `services.extraction_value` and `quotes_from_extracted_data`.
- **Tool arrives without `call_ref`:** the tool route also accepts `execution_id`, so the order is still matched.
- **Amounts look off:** set `COST_UNIT_TO_INR` from the wallet movement after one call (US cents → ~0.92, not 0.01).
- **Demo fallback:** `make fake`, and tell the judges it is simulated.

Spending is capped at Rs 75 per order and Rs 400 per day (limits in `.env`; the free $5 is about Rs 460). Only numbers in `VERIFIED_NUMBERS` can be dialed.

---

## G. Free-tier live demo, start to finish (added 2026-10-27)

This is the path that actually worked on our free Bolna account ($5 credit, 2 calls at a time, verified
numbers only). Sections A–F above still apply; this section is the short, current version. All commands
run from `dalaal/` with the virtual environment active:

```bash
cd dalaal
source .venv/bin/activate        # without this, `python` is the system one and imports fail
```

### G1. One-time setup (already done once; redo only on a new machine or a new Bolna account)
1. In the Bolna dashboard, verify every number you will dial: **User Profile → Verified Numbers** (OTP).
   We use: owner `+917975113319`, Kumar `+918983004130`, Ramesh `+919311509800`.
2. Install a tunnel: `sudo pacman -S cloudflared` (or ngrok).
3. `python scripts/go_live.py` once to create `.env`, then put `BOLNA_API_KEY` in it yourself.
4. In the Bolna dashboard, open each agent (Agent Studio) and:
   - **Tools tab**, both supplier agents (round 1 and round 2): add the tool from `build/submit_quote_tool.json`.
   - **Extractions tab**: add the entries from `bolna/extractions.md`: `quotes_json` and `do_not_call` on both
     supplier agents, `approval` on the owner approval agent, `confirmed` on the booking-confirmation agent
     (`order_json` on the intake agent only if you use voice ordering).

   Without the tool and extractions, calls happen but **no prices are saved** and the order fails with "no quotes".

### G2. Every session (three terminals)
```bash
# terminal 1: the server
uvicorn app.main:app --port 8000

# terminal 2: the tunnel. KEEP IT RUNNING: its URL is built into all six agents.
bash scripts/tunnel.sh            # copy the https://….trycloudflare.com URL
```
If the tunnel URL changed since last time (it does every time cloudflared restarts):
```bash
# terminal 3
# 1. put the new URL in .env as PUBLIC_BASE_URL
python scripts/render_bolna_files.py
python scripts/update_agents.py   # updates prompts + webhook URL on the existing agents; keeps tools/extractions
```
Then re-check the **Tools tab**: the `submit_quote` tool's URL is set in the dashboard, so change it to the new
URL there too (`build/submit_quote_tool.json` shows the exact value).

Check everything is ready:
```bash
python scripts/check_setup.py     # expect: Concurrency limit 2, Verdict OK
python scripts/go_live.py owner=+917975113319 kumar=+918983004130 ramesh=+919311509800
                                  # write numbers WITHOUT spaces; safe to re-run; ends with "READY for a live test"
```
Restart terminal 1 (uvicorn) if `go_live.py` changed `.env`.

### G3. Rehearse for free (do this as often as you like)
```bash
PROVIDER=fake FAKE_DELAY_SECONDS=1.5 uvicorn app.main:app --port 8001
```
Open http://localhost:8001. Same dashboard, simulated suppliers, no calls, no credit used. The header badge says
**SIMULATED suppliers**.

### G4. One real test call (~1 minute of credit) before any real order
```bash
python scripts/place_test_call.py --to +918983004130 --wait     # Kumar's number; --wait follows it to the end
```
The Kumar teammate answers and gives prices for onions and oil, e.g. "pyaaz pachchis rupaye kilo, tel saath rupaye litre".
Then open http://localhost:8000/debug/calls and check:
- a price shows up (first "heard live", then "confirmed" after the call ends). No price → the tool or extractions in G1.4 are missing;
- the agent asked about **both** items before the 60-second cut-off. If it got cut off, raise the round-1 agent's
  call time limit to 90 s in the Bolna dashboard (the API cannot change it; a 61–90 s call costs 2 minutes).

### G5. The live demo
1. Open http://localhost:8000. The header badge must say **LIVE calls**.
2. **New order** card: it is pre-filled with the demo order (20 kg onions, 10 litre oil, by 07:00, budget ₹1,200).
   Change, add or remove items as you like. Below the form it shows who will be called, in which pairs, and the
   estimated credit. Use a budget of **1000** if you want to show the owner-approval call.
3. Click **Start calling** and confirm. What happens, in order:
   - **Round 1**: suppliers are grouped by what they sell and called two at a time ("Pair 1", "Pair 2", …). Each card shows
     ringing → on the call (with a timer) → each price the moment the agent confirms it, with the supplier's own words.
     A later pair is told the best real price from earlier pairs. The full transcript appears when each call hangs up.
     (Bolna does not send words during a call, so there is no word-by-word transcript.)
   - **Ranking** fills in when round 1 is done.
   - **Round 2**: the best suppliers are called back with a real competing price; new prices appear on their cards.
   - **Owner & booking**: approval call (only if over budget or a price is unconfirmed), the booking confirmation with
     the supplier, then the owner's report call.
   - **Receipt**: appears at the top once booked. **Print / save PDF** prints only the receipt.
4. **Stop order** (top right) cancels everything still pending if something goes wrong.

What the teammates do: answer, give prices (Kumar and Ramesh should give different ones), in round 2 accept a lower
price, on the confirmation call say "haan" and repeat the quantities, and the owner says "haan" on the approval call.

### G6. Budget
- About 6¢ (₹5.5) per call minute; every call is capped at 60 s, i.e. one billed minute.
- With Kumar and Ramesh only: a full order is about 6 calls ≈ ₹33. Gowda and Lakshmi have placeholder numbers and are skipped.
- After the first test call the wallet was ₹450-ish (`python scripts/check_setup.py` shows it; the raw value is in cents).
- Orders the wallet cannot cover are refused before anything is dialed. Do all rehearsals in fake mode (G3).

### G7. Things that bit us (so they don't again)
| Symptom | Fix |
|---|---|
| `go_live.py` saved a number as `+91` | You typed spaces. Write `+919311509800`. The scripts now refuse incomplete numbers. |
| Bolna refused agents: "Voice > Language is required" / "anushka is not available" | Fixed in the template (`language: hi`, voice `kavya`). |
| `UNIQUE constraint failed: calls.execution_id` in fake mode | Fixed; was fake ids repeating after a restart. |
| `check_setup.py` crashed on `concurrency` | Fixed; Bolna returns `{"max": 2, "current": 0}`. |
| `ModuleNotFoundError: httpx` | The virtual environment is not active: `source .venv/bin/activate`. |
| Prices never appear | Tool and extractions not attached (G1.4), or the tool still has an old tunnel URL (G2). |

---

## H. The one-command way (added 2026-10-30, replaces the manual steps in G1–G2)

`scripts/start.py` now does everything that used to need editing `.env` or clicking in the Bolna dashboard:
the virtual environment, the API key prompt, the tunnel and its URL, creating or updating the six agents,
**attaching the `submit_quote` tool and creating the extractions through the API**, starting the server and the
readiness check. When the tunnel URL changes after a restart, the next run pushes it to Bolna by itself.
Sections A–G are kept for reference.

The only manual thing left: the phone numbers must be verified in the Bolna dashboard
(**User Profile → Verified Numbers**, OTP). The free tier only dials verified numbers, and there is no API for it.

### H1. First time
```bash
sudo pacman -S cloudflared        # once; or install ngrok and run `ngrok config add-authtoken <token>`
cd ~/Bolna-Hackathon/dalaal
python3 scripts/start.py owner=+917975113319 kumar=+918983004130 ramesh=+919311509800
```
It asks for the Bolna API key once (typing is hidden) and saves it in `.env`. Write the numbers without spaces.
You do not need to activate the virtual environment: the script does it (and creates it on a new machine).

### H2. Every time after
```bash
cd ~/Bolna-Hackathon/dalaal
python3 scripts/start.py          # or: make live
```
Wait for `READY for live calls.`, then open http://localhost:8000. **Ctrl+C** stops the server and the tunnel together.
If it prints a `[XX]` line, the line says what to fix; fix it and run the same command again.

### H3. Rehearsal, free
```bash
python3 scripts/start.py --fake   # or: make fake   → http://localhost:8001
```
Simulated suppliers, no tunnel, no key, no credit, and its own database (`dalaal_rehearsal.db`), so rehearsal orders
never show up on the live board.

### H4. The demo itself
Same as G4–G5: one test call first (`.venv/bin/python scripts/place_test_call.py --to +918983004130 --wait`), then on the dashboard fill in the order,
check the pairs it will call, and click **Start calling**.

### H5. Free-tier limitation (say this in the pitch)
Because of the free-tier restrictions we are **not able to run the full demo live, which is around 2 minutes**:
only 2 calls at a time, only verified numbers (so only our 3 teammates' phones, not four suppliers), $5 of credit
(about 80 call-minutes) and 60-second calls. Live, we show one pair (Kumar and Ramesh) through round 1, round 2,
booking and the receipt; the full four-supplier flow runs in rehearsal mode on the same dashboard. Details are in
`dalaal/README.md` under "Free-tier limits".

---

## I. Hang-ups, and what counts as a failed call (added 2026-10-30)

**Hanging up is not a failure by itself.** If you (playing a supplier or the owner) finish the conversation and cut
the call early, that is fine: Bolna still marks the call `completed` and the code reads what was said *before* the
hang-up. What matters:

- **Round 1 / round 2:** a price you confirmed before hanging up is used. If you hang up before giving any price, that
  supplier simply has no quote.
- **Booking confirmation:** say a clear **"haan" / "yes"** to the order and the total, then hang up whenever you like:
  the order is booked. It fails only if you say no, change a quantity, price or delivery time, the total you agree
  differs from ours, or you hang up **before** saying yes. Then the runner-up supplier is tried.
- **Owner approval:** only a clear yes books; no answer or "unclear" never books.
- **Real failures:** the call never connects (`no-answer`, `busy`, `failed`) or goes to voicemail. Round-1 suppliers
  get one retry if there is time.

Each call card on the dashboard now says why it ended: *they hung up*, *ended after silence* (10 s of nobody talking),
or *hit the time limit* (60 s).

Why this section exists: in the test on 2026-10-30 the supplier said yes twice and hung up after "thank you", but the
order was marked failed. The hang-up was not the cause. Bolna's extractor wrote its answer as a sentence instead of
JSON, and the code could not read it. That is fixed (yes/no answers are now read from words, JSON or sentences), and
the confirmation questions are now simple one-word / one-number questions.

The same day the confirmation agent said *it* would deliver the goods. The prompts now spell out the roles: the
kitchen is the buyer, the supplier delivers **to** the kitchen, and the agent asks "Kya aap 7 baje tak … ko delivery
kar denge?". Restart `python3 scripts/start.py` to load the code fix; the prompts are already updated on Bolna.

---

## J. Shorter round-1 calls, and Hindi / English / Kannada (added 2026-10-30)

**Round 1 is shorter.** The agent now has a fixed plan: one question for all items and the delivery time, one short
follow-up only if needed (credit / delivery charge), a one-sentence read-back of *your* prices, then "Dhanyavaad". It is
told to speak about 30 seconds in total (under 75 words) and leave the other ~30 seconds to the supplier. As the
supplier, answer everything in one go ("pyaaz pachchis, tel saath, subah saat baje tak, udhaar nahi") and the call ends
well inside the 60-second limit.

**Languages.** Every agent now speaks Hindi, English and Kannada:
- A call starts in that person's language. Kumar, Ramesh and the owner are Hindi; Gowda is Kannada.
- If you switch language during the call, the agent switches too (Bolna does this automatically).
- To make a teammate's calls start in Kannada or English, add it to the start command once:
  ```bash
  python3 scripts/start.py kumar.lang=kn          # kn = Kannada, en = English, hi = Hindi
  python3 scripts/start.py ramesh.lang=en kumar=+91XXXXXXXXXX   # can be combined with new numbers
  ```
  It is saved; later runs keep it. The start-up list shows each person's language in brackets.

Status: Hindi is tested on real calls. English and Kannada are set up and accepted by Bolna on all agents, but not yet
tried on a real call: do one test call in each before relying on them in the demo (about 1 minute of credit each).
