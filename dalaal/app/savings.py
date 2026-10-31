"""The savings number and the time saved (ticket #28).

Baseline, in order of honesty (Bible section 3):
  1. the owner's own last paid price for each item        <- preferred
  2. the owner's usual supplier's round-1 quote total      <- fallback
  The highest quote is NEVER used: it flatters the number and means nothing.
An order that saved nothing reports zero, not a negative spun as a win; the raw figure is kept so
the aggregate can stay honest.
"""

from __future__ import annotations

from dataclasses import dataclass

from app import parsing
from app.ranking import OrderLine


@dataclass
class Baseline:
    total: float
    kind: str  # owner_last_paid_price | usual_supplier_quote

    @property
    def label(self) -> str:
        return {
            "owner_last_paid_price": "vs what you paid last time",
            "usual_supplier_quote": "vs your usual supplier's quote today",
        }.get(self.kind, self.kind)


def baseline_from_owner_prices(lines: list[OrderLine], usual_prices: dict | None) -> Baseline | None:
    """Needs a usual price for EVERY item; a partial baseline would understate or overstate it."""
    if not usual_prices:
        return None
    total = 0.0
    for ln in lines:
        entry = usual_prices.get(ln.name)
        if not isinstance(entry, dict) or entry.get("price") is None:
            return None
        u = parsing.normalise_unit(str(entry.get("unit", "")))
        if u is None or u.to_base is None or u.base != ln.base_unit:
            return None
        per_base = float(entry["price"]) / u.to_base
        total += per_base * (ln.base_quantity or 0.0)
    return Baseline(round(total, 2), "owner_last_paid_price")


def baseline(lines: list[OrderLine], usual_prices: dict | None, usual_supplier_total: float | None) -> Baseline | None:
    return baseline_from_owner_prices(lines, usual_prices) or (
        Baseline(round(usual_supplier_total, 2), "usual_supplier_quote") if usual_supplier_total else None
    )


def savings(baseline_total: float | None, booked_total: float | None) -> dict:
    """{'savings': >= 0, 'raw': can be negative}. No baseline means no claim."""
    if baseline_total is None or booked_total is None:
        return {"savings": None, "raw": None}
    raw = round(baseline_total - booked_total, 2)
    return {"savings": max(0.0, raw), "raw": raw}


def time_saved_minutes(manual_minutes_per_order: float, owner_call_seconds: float) -> float:
    """Minutes of phone work returned: what the owner said an order costs by hand, minus the
    time they actually spent on Dalaal's intake, approval and callback calls."""
    return round(max(0.0, manual_minutes_per_order - owner_call_seconds / 60.0), 1)
