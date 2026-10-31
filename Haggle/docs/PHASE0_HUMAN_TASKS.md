# Phase 0 — the parts only people can do

Code cannot do these. Each maps to a ticket in the build map. Do them today.

## #1 Paid plan / sponsor credits, and your real limits

1. Post in Bolna's builder Slack. Suggested message:

   > Hi Bolna team — we're building **Dalaal** for the Buildathon (an agent that phones a small business's suppliers in parallel, then calls the best two back with a real counter-offer). Our demo needs 4 concurrent outbound calls, and trial accounts are capped at 2. Could you raise our concurrency and/or add sponsor credits to our account (`<your account email>`)? Happy to share the architecture.

2. Put your API key in `.env`, then run `python scripts/check_setup.py`. Paste the output into `NOTES.md`.
3. Concurrency 2 is enough: round 1 calls suppliers in pairs that sell the same items, and the second pair is anchored with the first pair's confirmed prices (`orchestrator.plan_round1_waves`). More concurrency only makes the waves bigger.

## #2 Registration and application form

- Register the team (up to 4 people).
- Submit the application form: team size, your details, city, college or company, LinkedIn or GitHub, project name (**Dalaal**), how long you've worked on it, and where voice AI comes in.
- Save the confirmation (screenshot or email). Submission deadline is **30 Oct** (official close 31 Oct).

## #3 Number, key and verified teammates

1. Create the Bolna account and API key.
2. Connect or buy an outbound number in the Bolna dashboard. Indian 140/160-series numbers need DLT registration and KYC, so start today. Fallback: the Web Call SDK runs an agent in the browser with no phone number.
3. **Verify every teammate's phone number** in Bolna. On a trial, only verified numbers can be dialed.
4. Place one manual test call from the dashboard to a verified teammate.
5. Ask Bolna which number and registration to use for **supplier calls** and save the answer in `NOTES.md` (ticket #23).

## #5 Owner interviews

Book 3 to 5 restaurant or cloud-kitchen owners. Ask:

1. How many supplier calls do you make on a typical morning? How many minutes does that take?
2. How do you decide who to order from today?
3. Do your suppliers give you credit? For how many days?
4. What do you usually pay per kg for onions and per litre for cooking oil right now?
5. How often is a delivery late, and what does that cost you?
6. Would you let an automated assistant phone your suppliers for you? What would worry you?
7. What would you pay per month for it? (Get a number.)
8. Can we try a pilot, or may we make one real supplier call with your permission?

Record each answer with the date and the person's first name. One real quote and one real number are worth more than a polished dashboard in the interview round.

## #6 Playing the suppliers

Open `data/personas.json`. Assign each of the four personas to a teammate (replace `"TBD teammate"`), and replace the placeholder phone numbers with each teammate's **verified** number. Teammates play the **persona, not a script**: unscripted replies prove the agent is real.

| Persona | Language | Plays | What they do |
| --- | --- | --- | --- |
| Kumar Stores | Hindi | Cheapest, unreliable | Quotes ₹25/kg onions, ₹60/L oil, promises 7:00 am. Nothing else |
| Ramesh Traders | Hindi | The haggler | Quotes ₹26 and ₹62. In round 2 drops to ₹25 and ₹60 when told a lower real quote exists |
| Gowda Vegetables | Kannada | The Kannada call | Quotes ₹27 and ₹64, delivers 6:45 am |
| Lakshmi Agencies | Hindi | Out of stock | Has onions at ₹28 but no oil |
