# Architecture

```mermaid
flowchart LR
  Owner([Owner]) -- voice or POST /api/orders --> Intake[Intake agent]
  Intake -- order_json extraction --> Orch
  subgraph App[Dalaal server - FastAPI]
    Orch[orchestrator.tick<br/>idempotent, locked]
    Rank[ranking.py / savings.py<br/>pure functions]
    Neg[negotiation.py<br/>real-prices-only guard]
    Guards[guards.py + safety.py<br/>cost, concurrency, kill switch, verified numbers]
    DB[(Database<br/>single source of truth)]
    Orch --> Rank & Neg & Guards
    Orch <--> DB
  end
  Orch -- place_call --> Prov{Provider}
  Prov -- PROVIDER=bolna --> Bolna[Bolna voice agents<br/>supplier R1/R2, approval, confirm, callback]
  Prov -- PROVIDER=fake --> Fake[FakeProvider<br/>personas.json]
  Bolna -- status webhook + extracted_data --> WH[/webhook/bolna/]
  Bolna -- submit_quote tool (mid-call) --> TQ[/tools/submit_quote/]
  Fake -. same code paths .-> WH & TQ
  WH & TQ --> DB
  DB --> API[/api/orders/id/state + SSE stream/] --> Board[Live dashboard /]
  Loop[background loop: watchdog polls stale calls, dispatches pending calls] --> Orch
```

**Order states:** DRAFT → COLLECTING_R1 → RANKED → NEGOTIATING_R2 → RERANKED → (AWAITING_APPROVAL) → BOOKING → BOOKED → REPORTED, any → FAILED.
Every move is `UPDATE … WHERE state IN (allowed)`, so two simultaneous events cannot both win.

**Where each safety rule lives:** real prices only → `negotiation.assert_real_offers`; no booking without a yes when over budget/partial/unconfirmed
→ `orchestrator.approval_reasons`; confirmation must match quantities and total → `orchestrator.confirm_result`; spend/concurrency → `guards.py`;
only teammates dialed in testing → `safety.py` + `select_suppliers`.
