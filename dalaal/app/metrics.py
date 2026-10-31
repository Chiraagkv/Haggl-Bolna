"""The numbers for the pitch and the interviews (ticket #44). Everything is computed from the
database, so it is whatever actually happened; nothing is typed in."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import orders
from app.models import Call, Order, Quote


def compute(session: Session) -> dict:
    all_orders = list(session.scalars(select(Order)))
    done = [o for o in all_orders if o.state == orders.REPORTED]
    failed = [o for o in all_orders if o.state == orders.FAILED]
    finished = done + failed
    saved = [o.savings for o in done if o.savings is not None]
    times = [(o.finished_at - o.created_at).total_seconds() for o in done if o.finished_at and o.created_at]
    calls = list(session.scalars(select(Call).where(Call.status_rank >= 6)))
    sup_calls = [c for c in calls if (c.kind or "").startswith("supplier")]
    reached = [c for c in sup_calls if c.status == "completed" and not c.answered_by_voicemail]
    fails: dict[str, int] = {}
    for o in failed:
        fails[o.failure_reason or "unknown"] = fails.get(o.failure_reason or "unknown", 0) + 1
    quotes = session.scalar(select(func.count()).select_from(Quote)) or 0
    flagged = session.scalar(select(func.count()).select_from(Quote).where(Quote.flagged.is_(True))) or 0

    def avg(xs):
        return round(sum(xs) / len(xs), 2) if xs else None

    return {
        "orders": len(all_orders), "booked": len(done), "failed": len(failed),
        "completion_rate": round(len(done) / len(finished), 3) if finished else None,
        "failure_reasons": fails,
        "avg_savings_inr": avg(saved), "total_savings_inr": round(sum(saved), 2) if saved else 0,
        "orders_with_zero_savings": sum(1 for s in saved if s == 0),
        "avg_time_saved_min": avg([o.time_saved_min for o in done if o.time_saved_min is not None]),
        "avg_seconds_order_to_report": avg(times),
        "avg_cost_per_order_inr": avg([o.cost_incurred for o in finished if o.cost_incurred]),
        "supplier_calls": len(sup_calls),
        "supplier_reach_rate": round(len(reached) / len(sup_calls), 3) if sup_calls else None,
        "quotes": quotes, "quotes_flagged": flagged,
        "note": "Savings use the owner's last paid price (or the usual supplier's quote), never the highest quote.",
    }
