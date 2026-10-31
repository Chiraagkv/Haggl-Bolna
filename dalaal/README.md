# Dalaal

An AI procurement agent that phones a small business's suppliers in Hindi, Kannada or English. It runs round 1 (parallel quote calls), round 2 (a counter-offer to the best two, using real quotes only), an owner approval call if needed, booking, and a final callback with the savings.

This repo follows `dalaal-build-map.md` (51 tickets) and `dalaal-project-bible.md` (Revision 5).

## Run it (one command)

```bash
cd dalaal
python scripts/start.py owner=+91XXXXXXXXXX kumar=+91XXXXXXXXXX ramesh=+91XXXXXXXXXX   # first time
python scripts/start.py                                                               # every time after
python scripts/start.py --fake                                                        # free rehearsal, no calls
```

Then open http://localhost:8000 (rehearsal: http://localhost:8001). `start.py` creates the virtual environment, asks
for the Bolna API key once, starts the tunnel, writes its URL to `.env`, creates or updates all six Bolna agents
**including the `submit_quote` tool and the extractions** (through the API, no dashboard steps), starts the server and
prints a readiness list. Ctrl+C stops everything. A new tunnel URL after a restart is pushed to Bolna automatically.

Needs: `cloudflared` (or `ngrok`) installed, and the phone numbers already verified in the Bolna dashboard
(User Profile → Verified Numbers): on the free tier that is the only thing the code cannot do for you.

## Free-tier limits: what we can and cannot show live

We are on Bolna's free tier and cannot buy a paid plan. **Because of the free-tier restrictions, we are not able to run
the full demo live, which is around 2 minutes.** The restrictions that stop it:

| Free-tier restriction | Effect on the demo |
| --- | --- |
| 2 calls at once | Round 1 cannot call all four suppliers together. We call them in pairs that sell the same items, so it takes longer |
| Only numbers verified in the dashboard can be called | Every "supplier" and the owner must be a teammate's own phone. We have 3 (owner, Kumar, Ramesh), so Gowda and Lakshmi are skipped live |
| $5 of credit once (about 80 call-minutes) | A full order is 6–10 calls. We can afford a few live runs, not repeated rehearsals |
| Calls capped at 60 s to stay at one billed minute | The agents must be brief; a long haggle gets cut off |

What we do instead: the **live** demo runs the real flow with one pair (Kumar and Ramesh): round 1, round 2, booking
confirmation, owner report and the receipt. The **full** four-supplier flow (two pairs, a split basket, failures) runs
in rehearsal mode (`python scripts/start.py --fake`) on the same dashboard, clearly labelled *SIMULATED suppliers*.

## Status

| Phase | Tickets | State |
| --- | --- | --- |
| 0 — Unblock & foundations | #1–#6 | Code done. Human tasks in `docs/PHASE0_HUMAN_TASKS.md` |
| 1 — One call works | #7–#14 | Code done and tested offline. **Live proof needs your key, a number and a teammate** (`docs/PHASE1_RUNBOOK.md`) |
| 2 — Data & state | #15–#18 | Done: models, order state machine, event feed, spend and concurrency guards |
| 3–4 — Calls & ranking | #19–#30 | Done: supplier selection, dialer with our own queue, round-1 deadline, watchdog polling, no-answer/voicemail, do-not-call, **FakeProvider**, scored ranking, split basket, savings baseline |
| 5 — Orchestrator | #31–#36 | Done: intake, round 2 with the real-prices-only guard, approval, booking confirmation with runner-up retry, owner callback, notifier stub |
| 6–8 — Dashboard, hardening, docs | #37–#51 | Done: live board (`/`), SSE feed, failure-injection tests, metrics, runbooks, demo script |

**What is proven and what is not.** Everything above runs and is tested (190+ tests) against a scripted
fake provider that goes through the same webhook and tool code paths. Nothing has been run against live
Bolna yet: see `docs/LIVE_TEST_RUNBOOK.md` for the order to prove it, and the "UNVERIFIED" notes in
`docs/BOLNA_GOTCHAS.md`.

## Languages: Hindi, English and Kannada

Every agent speaks all three (Bolna `multilingual_config`, set up by `app/bolna_setup.py`). Each language has its own
speech recognizer (Sarvam `saaras:v4`), voice (Sarvam `bulbul:v3`, voice *kavya*) and welcome message.
- **A call starts in the person's language**: each supplier and the owner has one (`hi`, `en` or `kn`; Gowda is Kannada),
  passed to Bolna with every call as `agent_language`.
- **Switching mid-call is automatic**: if the person switches to another of the three, Bolna switches the agent.
  The prompts no longer tell the agent to switch (Bolna's docs say to leave that to Bolna).
- Set someone's language with the start command: `python3 scripts/start.py kumar.lang=kn` (or `en`, `hi`).
- Prices and quantities are read the same way in every language; the dashboard and receipt stay in English.
- **Live-tested so far: Hindi only.** Bolna accepted and stored the English and Kannada setup on all six agents
  (2026-10-30), but no English or Kannada phone call has been made yet. Test one before the demo.

## How a call's outcome is decided (hanging up is not a failure)

**Hanging up does not by itself make a call fail.** Whoever ends the call (the supplier, the owner, the agent, a
silence timeout or the 60-second limit), Bolna still marks it `completed` and runs the extractions on the transcript.
The outcome comes only from **what was said before the call ended**:

| How the call ended | What the code does |
| --- | --- |
| Supplier gave prices / said yes, then hung up | Counts. Prices are used; a yes on the confirmation call books the order |
| Hung up (or went silent) **before** giving a price or a clear yes | Nothing usable: that supplier has no quote, or the booking is not confirmed and the runner-up is tried |
| Hit the 60-second limit mid-sentence | Whatever was confirmed before the cut-off counts; the rest is missing |
| Never connected: `no-answer`, `busy`, `failed` | Failure for that call. A round-1 supplier gets one retry if there is time |
| Voicemail picked up | Treated as no answer (one retry in round 1) |

On the confirmation call, an order is booked only if the supplier clearly said **yes**, did **not** change a quantity,
price or delivery time, and any total they agreed is within 5% (or ₹5) of ours (`orchestrator.confirm_result`). Owner
approval books only on a clear **yes**; "unclear" or no answer never books. Yes/no answers are read whether Bolna returns
one word, JSON or a full sentence (`services.yes_no`): on 2026-10-30 a confirmed order was wrongly failed because the
answer came back as a sentence, and that is fixed. The dashboard shows why each call ended ("they hung up", "ended after
silence", "hit the time limit").

## When you have the Bolna key (the older, step-by-step path; `scripts/start.py` replaces it)

```bash
bash scripts/tunnel.sh                      # copy the https URL
python scripts/go_live.py                   # first run creates .env; put BOLNA_API_KEY and PUBLIC_BASE_URL in it
python scripts/go_live.py owner=+91… kumar=+91… ramesh=+91… gowda=+91… lakshmi=+91…   # your verified teammates
uvicorn app.main:app --port 8000            # open http://localhost:8000, GET /api/preflight shows what is left
```

`go_live.py` seeds the numbers, writes `VERIFIED_NUMBERS` and a `TOOL_SECRET`, creates or updates all six agents (with the
`submit_quote` tool and the extractions, through the API) and writes their ids to `.env`, then prints a checklist.
Then follow `docs/LIVE_TEST_RUNBOOK.md` from Step 2.

## Try it in 30 seconds, no key, no phone

```bash
pip install -r requirements-dev.txt
python scripts/run_demo.py                                  # happy path, printed
python scripts/run_demo.py --fail kumar=no-answer ramesh=refuses_confirm
PROVIDER=fake FAKE_DELAY_SECONDS=1.5 uvicorn app.main:app   # open http://localhost:8000 and click "Start calling"
```

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env              # then add BOLNA_API_KEY
python -m pytest -q               # all green, no network, no phone calls
uvicorn app.main:app --reload     # http://localhost:8000/health
```

Then:

```bash
bash scripts/tunnel.sh            # ngrok or cloudflared; copy the https URL into PUBLIC_BASE_URL
curl https://<your-url>/health    # must answer from outside your machine (ticket #4 test)
python scripts/check_setup.py     # reads your real concurrency + wallet (ticket #1)
```

Phase 1, free rehearsal (no Bolna, no phone, no cost):

```bash
uvicorn app.main:app --port 8000
python scripts/simulate_call.py   # replays a call; then open http://localhost:8000/debug/calls
```

Optional shared Postgres: `docker compose up -d db`, then set `DATABASE_URL` as shown in `.env.example`.

## Layout

```
app/            FastAPI app. orchestrator.py is the conductor; ranking.py, savings.py, negotiation.py are pure functions;
                providers.py has BolnaProvider and FakeProvider; api.py + static/dashboard.html is the live board
bolna/          Agent config, prompt, submit_quote tool and extraction templates (rendered into build/)
scripts/        check_setup, tunnel, render_bolna_files, create_agents, seed_demo, run_demo, metrics, place_test_call, simulate_call
data/           personas.json — seed suppliers and the demo order
docs/           LIVE_TEST_RUNBOOK.md, DEMO_SCRIPT.md, SUBMISSION_CHECKLIST.md, INTERVIEW_PREP.md, PHASE0/1 notes, BOLNA_GOTCHAS.md
tests/          pytest; no test places a phone call
NOTES.md        the team's single page of facts (limits, numbers, day-1 answers)
```

## Rules the code follows

- The database is the only source of truth. No business logic in prompts.
- Every webhook is safe to receive twice.
- Real calls only to verified teammate numbers (`VERIFIED_NUMBERS`). Tests never call anyone.
- Free-tier friendly: round 1 runs in pairs of suppliers who sell the same items (2 concurrent calls), every call
  fits one billed minute, and an order the wallet cannot cover is refused before anything is dialed.
- A quote heard live is provisional; the extraction at `completed` confirms or corrects it.
- Unknown units and prices are flagged, never guessed.
- Never commit `.env`.
