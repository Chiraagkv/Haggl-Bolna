# Submission checklist (closes 31 Oct; aim to submit 30 Oct)

- [ ] `pytest` is green on a clean checkout (`pip install -r requirements-dev.txt && pytest -q`)
- [ ] `.env` is NOT in the repo; `.env.example` is
- [ ] README top table is true: say plainly what ran live and what only ran against the fake provider
- [ ] Live proofs done or honestly marked not done: #7 agent created, #10 webhook, #11 mid-call tool, #13 keyword effect, #14 first real quote
- [ ] One real end-to-end recording (screen + audio) or, failing that, the fake-provider run clearly labelled
- [ ] 60-second video: problem → live board → result number
- [ ] Numbers on slides come from `python scripts/metrics.py`, not from memory; hand-typed reliability histories are labelled "demo data"
- [ ] The three claims you can defend: real prices only (guard + tests), never books without a yes when over budget (tests), savings vs owner's own last price
- [ ] Compliance line: AI disclosed on every call, human offered, do-not-call honoured; calling-number answer from Bolna written in NOTES.md
- [ ] Interview prep read (5-7 Nov); finale 20 Nov Bengaluru: bring a phone + hotspot, run the fake demo as the backup
