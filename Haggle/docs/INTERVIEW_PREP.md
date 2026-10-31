# Interview prep — likely questions, honest answers

**What is the hard part?** Not the voice. It is trust: a purchasing agent that books money must never invent a price or
book something the owner did not approve. So the rules are code, not prompts: `negotiation.assert_real_offers`, the
approval rule in `orchestrator.approval_reasons`, the quantity/total check in `confirm_result`, spend and concurrency guards in `guards.py`.

**How do you rank suppliers?** Expected cost = quoted total + delivery fee − value of credit days + P(late) × cost of being late.
P(late) is a smoothed estimate (late+1)/(orders+4) so a new supplier is not trusted blindly. The numbers in the demo (₹300 lateness cost,
2%/month credit value) are assumptions we say are assumptions; they are config.

**How do you measure savings honestly?** Against what the owner paid last time, or the usual supplier's quote today. Never against the highest quote. A zero-saving order shows zero.

**What happens when a call fails?** No answer/voicemail: that supplier is skipped. Lost webhook: the watchdog polls the call.
Supplier refuses to confirm: runner-up (bounded by `MAX_BOOKING_ATTEMPTS`). Everyone silent: the order fails cleanly with a reason and nothing is booked.

**What did you not test live?** (Be specific. See the README status and your NOTES.md.) The fake provider proves the logic and the
failure handling; it does not prove Bolna's real payload shapes or how voice recognition copes with real mandi noise.

**What would you build next?** Real delivery tracking to feed reliability scores, WhatsApp for the owner, more items per order, Kannada-first prompts tested with real suppliers.
