# Extractions on each agent

**Created automatically** by `scripts/start.py` (via `app/bolna_setup.py` and Bolna's dispositions API) from
`bolna/extractions.json`, which is the source of truth: edit the questions there and re-run start.py. This page
explains them. The code reads each by its exact NAME, wherever Bolna nests it. All are Free Text.

| Agent | Name | Prompt (paste as is) |
|---|---|---|
| Supplier R1 and R2 | `quotes_json` | see `extraction_quotes_json.md` |
| Supplier R1 and R2 | `do_not_call` | `Did the person ask not to be called again? Answer exactly yes or no.` |
| Owner approval | `approval` | `Did the owner clearly approve booking this order? Answer with one word: yes, no or unclear.` |
| Supplier confirm | `confirmed`, `confirm_changed`, `confirm_total`, `confirm_delivery_time` | yes/no, yes/no, a number, a time: see `bolna/extractions.json` |
| Owner intake (inbound) | `order_json` | `Return ONLY JSON: {"items": [{"name": "<English item, lowercase>", "quantity": <number>, "unit": "kg or litre or piece"}], "deadline": "<HH:MM 24h>", "budget": <rupees or null>}` |

What the code does with them (all in `app/orchestrator.py`):
- `confirmed` + `confirm_changed` + `confirm_total`: booked only on a clear yes, no changed terms, and a total within
  5% (or Rs 5) of ours; otherwise the booking is treated as failed and the runner-up is tried. Hanging up after
  saying yes is fine: see "How a call's outcome is decided" in the README.
- `approval`: only an explicit yes books. No answer or "unclear" never books.
- `order_json`: validated (positive quantity, known unit, readable deadline, sanity limit); a bad one is
  logged as `intake_rejected` and no order is created.

UNVERIFIED against live Bolna: the exact nesting of `extracted_data`. If it differs, `/debug/events`
shows the real payload and `services.extraction_value` is the one function to adjust.
