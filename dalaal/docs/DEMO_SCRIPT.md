# Demo script (3 minutes) — Dalaal

Run with the real agents if Step 3 of the live runbook passed; otherwise run the fake provider and **say so**
("suppliers are simulated here; this is the same code path the real calls use"). Judges forgive a simulated supplier; they do not forgive one passed off as real.

**Setup:** board open on a big screen (`/`), a teammate's phone on the table as "Kumar", another as the owner.

| Time | Do | Say |
|---|---|---|
| 0:00 | Owner (teammate) speaks the order in Hindi: "bees kilo pyaaz, das litre tel, kal subah saat baje tak." | "Priya runs a small kitchen. Every morning she spends about 15 minutes phoning four suppliers." |
| 0:20 | Board: Kumar and Ramesh ringing, quotes appear as they speak; then Gowda and Lakshmi | "Dalaal sorts suppliers by what they sell and calls them in pairs, in Hindi or Kannada, and says up front it is an AI. The second pair already hears the best real price from the first, so it bargains live." |
| 0:50 | Point at the ranking table | "Kumar is cheapest on paper, but late 2 of 3 times, so his expected cost is higher. Ramesh wins." |
| 1:15 | Round 2 badge | "Dalaal tells Ramesh a real price another supplier gave: 25. It never invents one, and a guard in code blocks it if it tried. Ramesh matches and adds 7 days' credit." |
| 1:45 | Over-budget → approval call rings the owner's phone | "It never books past your budget without your yes." (Owner says yes.) |
| 2:15 | Booking, then the callback | "It confirms quantities back with the supplier, then reports to Priya." |
| 2:35 | Result panel | "₹1,100, ₹200 less than Priya paid last time. We never count savings against the highest quote." |
| 2:50 | Metrics (`/api/metrics`) | "Each order costs about ₹X in calls and saves Priya about 14 minutes." |

**If a live call fails on stage:** click "Stop order", run the fake demo (`make fake`), say what happened. Do not retry live twice.

**Questions to be ready for:** what if the supplier does not want to talk to an AI (we disclose, offer the owner,
honour do-not-call); what stops it lying (real-prices-only guard, confirmations checked against quantities);
what does it cost (read it off the board); why not a marketplace (it replaces the vendor; Dalaal works with the suppliers the owner already trusts).
