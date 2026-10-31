# NOTES — facts the whole team needs in one place

Fill these in as you learn them. Date everything. Nothing here is a secret: put keys in `.env`.

## Account limits (ticket #1)

Run `python scripts/check_setup.py` and paste its output here.

- Read on:
- Concurrency limit:
- Wallet balance:
- Verdict:

Plan status: [ ] trial only  [ ] sponsor credits granted  [ ] paid plan active
Request sent in Bolna builder Slack on: ____ — reply: ____

## Phone numbers (ticket #3)

- Outbound number we call from:
- Provider (Plivo / Twilio / Exotel / Bolna-bought):
- Teammates' VERIFIED numbers (only these can be dialed on a trial):

| Teammate | Role | Number verified? |
| --- | --- | --- |
| | | |

## Calling rules (ticket #23)

Asked Bolna on ____ which number/registration to use for supplier calls. Written answer:

## Day-1 verifications (Phase 1)

| Question | Answer | Date | Fallback if no |
| --- | --- | --- | --- |
| Does `submit_quote` fire mid-call and the call continues? (#11) | | | Update dashboard at `completed` |
| Do per-call variables work for round 2? (#32) | | | Second agent for round 2 |
| Do webhooks reach us through the tunnel with extracted data at `completed`? (#10) | | | |
| Does `saaras:v4` keyword biasing improve price transcription? (#13) | | | |

## Decisions

- Tunnel tool: ngrok / cloudflared
- Database: SQLite (dev) / Postgres (shared)
