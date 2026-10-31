# The `quotes_json` extraction (set up in the Bolna dashboard)

This is the backstop that produces every confirmed quote at `completed`. Bolna's docs describe
extractions as a dashboard feature (the Extractions tab), so create it there.

**Category:** `Dalaal`
**Extraction name:** `quotes_json` (must match exactly: `app/services.py` looks for it)
**Answer type:** Free Text
**Expected format:** Text

**Extraction prompt** (paste as is):

```
From this call, list every item the supplier quoted a price for. Return ONLY a JSON array, no other text.
Each element: {"item": "<English item name, lowercase>", "unit_price": "<the price number as said, e.g. 25>",
"unit": "<kg, quintal or litre>", "available": <true or false>, "delivery_time": "<HH:MM or empty>",
"credit_days": <number, 0 if none>, "delivery_fee": <number, 0 if none>,
"what_they_said": "<the supplier's own words about this price>"}.
If no price was given, return [].
```

Also on the Extractions tab: set the **Webhook URL** to `<PUBLIC_BASE_URL>/webhook/bolna` (if the
agent was not created with `webhook_url`), leave "Trigger on statuses" on *All statuses*, and use
**Send test** to post a sample `completed` payload. It should appear in `GET /debug/events`.

**Shape we expect in the webhook** (from Bolna's output-format page):

```json
"extracted_data": { "Dalaal": { "quotes_json": { "subjective": "[{...}]", "objective": null, "confidence": 0.9 } } }
```

If the real payload differs, `/debug/events` shows it, and `quotes_from_extracted_data` in
`app/services.py` is the one function to adjust.
