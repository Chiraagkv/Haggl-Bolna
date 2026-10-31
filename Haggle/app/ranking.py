"""Scored ranking and split baskets (tickets #24-#27, #29). Pure Python, no database, no prompts.

The agent never decides who wins; this module does, and every number it uses is returned so the
dashboard can show it (Bible section 3).

    P(late)       = (late + a) / (late + on_time + a + b)                 a=1, b=3 by default
    credit_value  = quoted_total * credit_days * (rate_per_month / 30)
    expected_cost = quoted_total + delivery_fee - credit_value + P(late) * lateness_cost
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field

from app import parsing
from app.config import Settings


@dataclass(frozen=True)
class RankConfig:
    lateness_cost: float = 300.0
    prior_a: float = 1.0
    prior_b: float = 3.0
    credit_rate_per_month: float = 0.02
    split_min_saving: float = 60.0
    missing_delivery_ok: bool = False

    @classmethod
    def from_settings(cls, s: Settings) -> "RankConfig":
        return cls(s.lateness_cost_inr, s.late_prior_a, s.late_prior_b, s.credit_rate_per_month,
                   s.split_min_saving_inr, s.treat_missing_delivery_time_as_ok)


@dataclass
class ItemQuote:
    price_per_base: float
    base_unit: str
    available: bool = True
    unconfirmed: bool = False  # heard only through the live tool, not yet confirmed at `completed`


@dataclass
class SupplierInput:
    key: str
    name: str
    quotes: dict[str, ItemQuote]
    delivery_time: str | None = None   # latest time they promised across their quotes
    credit_days: float = 0.0
    delivery_fee: float = 0.0
    on_time: int = 0
    late: int = 0


@dataclass
class OrderLine:
    name: str
    quantity: float
    unit: str

    @property
    def base_unit(self) -> str | None:
        u = parsing.normalise_unit(self.unit)
        return u.base if u else None

    @property
    def base_quantity(self) -> float | None:
        u = parsing.normalise_unit(self.unit)
        return self.quantity * u.to_base if u and u.to_base else None


def order_lines(items: list[dict]) -> list[OrderLine]:
    return [OrderLine(str(i["name"]).strip().lower(), float(i["quantity"]), str(i["unit"])) for i in items]


# ------------------------------------------------------------------ small pure helpers
def parse_clock(text: str | None) -> int | None:
    """'07:00', '7:30 am', '6.30', '7 baje', '५:३०' -> minutes after midnight, or None."""
    if not text:
        return None
    t = parsing.normalise_digits(str(text)).lower()
    m = re.search(r"(\d{1,2})\s*[:.]\s*(\d{2})\s*(am|pm)?", t)
    if m:
        h, mi, ap = int(m.group(1)), int(m.group(2)), m.group(3)
    else:
        m = re.search(r"(\d{1,2})\s*(am|pm|baje|bje|o'?clock)?", t)
        if not m:
            return None
        h, mi, ap = int(m.group(1)), 0, (m.group(2) if m.group(2) in ("am", "pm") else None)
    if h > 23 or mi > 59:
        return None
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return h * 60 + mi


def p_late(on_time: int, late: int, a: float = 1.0, b: float = 3.0) -> float:
    return (late + a) / (late + on_time + a + b)


def credit_value(total: float, days: float, rate_per_month: float) -> float:
    return total * days * (rate_per_month / 30.0)


# ------------------------------------------------------------------------- scoring
@dataclass
class Scored:
    key: str
    name: str
    quoted_total: float
    delivery_fee: float
    credit_days: float
    credit_value: float
    p_late: float
    risk_cost: float
    expected_cost: float
    delivery_time: str | None
    on_time: int
    late: int
    lines: dict[str, float] = field(default_factory=dict)  # item -> line total
    unconfirmed: bool = False

    def breakdown(self) -> dict:
        r = lambda x: round(x, 2)  # noqa: E731
        return {
            "key": self.key, "name": self.name, "quoted_total": r(self.quoted_total),
            "delivery_fee": r(self.delivery_fee), "credit_days": self.credit_days,
            "credit_value": r(self.credit_value), "p_late": round(self.p_late, 4),
            "risk_cost": r(self.risk_cost), "expected_cost": r(self.expected_cost),
            "delivery_time": self.delivery_time, "on_time": self.on_time, "late": self.late,
            "lines": {k: r(v) for k, v in self.lines.items()}, "unconfirmed": self.unconfirmed,
        }


@dataclass
class Infeasible:
    key: str
    name: str
    reasons: list[str]
    covers: list[str]  # items they could supply (for split baskets / partial orders)


def meets_deadline(sup: SupplierInput, deadline: str, cfg: RankConfig) -> tuple[bool, str | None]:
    promised = parse_clock(sup.delivery_time)
    wanted = parse_clock(deadline)
    if promised is None:
        return (True, None) if cfg.missing_delivery_ok else (False, "no delivery time given")
    if wanted is not None and promised > wanted:
        return False, f"delivers {sup.delivery_time}, after the {deadline} deadline"
    return True, None


def _usable_item(sup: SupplierInput, line: OrderLine) -> tuple[ItemQuote | None, str | None]:
    q = sup.quotes.get(line.name)
    if q is None:
        return None, f"no quote for {line.name}"
    if not q.available:
        return None, f"{line.name} not available"
    if line.base_unit is None or q.base_unit != line.base_unit:
        return None, f"{line.name} priced per {q.base_unit}, order is in {line.unit}"
    return q, None


def score_supplier(lines: list[OrderLine], deadline: str, sup: SupplierInput, cfg: RankConfig) -> Scored | Infeasible:
    reasons: list[str] = []
    covers: list[str] = []
    line_totals: dict[str, float] = {}
    unconfirmed = False
    for line in lines:
        q, why = _usable_item(sup, line)
        if q is None:
            reasons.append(why or "unusable")
            continue
        covers.append(line.name)
        line_totals[line.name] = q.price_per_base * (line.base_quantity or 0.0)
        unconfirmed = unconfirmed or q.unconfirmed
    ok, why = meets_deadline(sup, deadline, cfg)
    if not ok:
        reasons.append(why or "late")
    if reasons:
        return Infeasible(sup.key, sup.name, reasons, covers)
    total = sum(line_totals.values())
    pl = p_late(sup.on_time, sup.late, cfg.prior_a, cfg.prior_b)
    cv = credit_value(total, sup.credit_days, cfg.credit_rate_per_month)
    risk = pl * cfg.lateness_cost
    return Scored(sup.key, sup.name, total, sup.delivery_fee, sup.credit_days, cv, pl, risk,
                  total + sup.delivery_fee - cv + risk, sup.delivery_time, sup.on_time, sup.late,
                  line_totals, unconfirmed)


@dataclass
class RankingResult:
    ranked: list[Scored]
    infeasible: list[Infeasible]


def rank_suppliers(lines: list[OrderLine], deadline: str, suppliers: list[SupplierInput], cfg: RankConfig) -> RankingResult:
    ranked: list[Scored] = []
    out: list[Infeasible] = []
    for s in suppliers:
        r = score_supplier(lines, deadline, s, cfg)
        (ranked if isinstance(r, Scored) else out).append(r)  # type: ignore[arg-type]
    ranked.sort(key=lambda r: (r.expected_cost, r.quoted_total, r.key))
    return RankingResult(ranked, out)


def ranked_lower_note(ranked: list[Scored]) -> dict | None:
    """If a cheaper-on-paper supplier lost on risk, say so (the dashboard's ranked-lower note)."""
    if len(ranked) < 2:
        return None
    winner = ranked[0]
    cheaper = [r for r in ranked[1:] if r.quoted_total < winner.quoted_total]
    if not cheaper:
        return None
    c = min(cheaper, key=lambda r: r.quoted_total)
    n = c.on_time + c.late
    hist = f"late {c.late} of last {n} orders" if n else "no delivery history"
    return {
        "key": c.key, "name": c.name, "cheaper_by": round(winner.quoted_total - c.quoted_total, 2),
        "text": f"{c.name}: cheapest, but {hist}, so the expected cost is higher "
                f"(Rs {c.expected_cost:.0f} vs Rs {winner.expected_cost:.0f}).",
    }


# ---------------------------------------------------------------- split baskets
@dataclass
class Decision:
    kind: str                       # single | split | partial | none
    assignments: dict[str, str]     # item -> supplier key
    suppliers: list[str]
    quoted_total: float = 0.0
    expected_cost: float = 0.0
    uncovered: list[str] = field(default_factory=list)
    per_supplier: list[dict] = field(default_factory=list)
    single_best_key: str | None = None
    single_best_expected: float | None = None
    split_saving: float | None = None
    note: str = ""

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in (
            "kind", "assignments", "suppliers", "quoted_total", "expected_cost", "uncovered", "per_supplier",
            "single_best_key", "single_best_expected", "split_saving", "note")}


def assignment_cost(lines_by_name: dict[str, OrderLine], assign: dict[str, str], sups: dict[str, SupplierInput],
                     cfg: RankConfig) -> tuple[float, float, list[dict]]:
    """(quoted_total, expected_cost, per-supplier breakdown) for an item->supplier assignment."""
    sub: dict[str, float] = {}
    for item, key in assign.items():
        q = sups[key].quotes[item]
        sub[key] = sub.get(key, 0.0) + q.price_per_base * (lines_by_name[item].base_quantity or 0.0)
    total = sum(sub.values())
    expected = total
    parts = []
    for key, amount in sub.items():
        s = sups[key]
        pl = p_late(s.on_time, s.late, cfg.prior_a, cfg.prior_b)
        share = amount / total if total else 0.0
        cv = credit_value(amount, s.credit_days, cfg.credit_rate_per_month)
        risk = pl * cfg.lateness_cost * share
        expected += s.delivery_fee - cv + risk
        parts.append({"key": key, "name": s.name, "subtotal": round(amount, 2), "delivery_fee": s.delivery_fee,
                      "credit_value": round(cv, 2), "p_late": round(pl, 4), "risk_cost": round(risk, 2),
                      "items": sorted(i for i, k in assign.items() if k == key)})
    return total, expected, parts


def decide(lines: list[OrderLine], deadline: str, suppliers: list[SupplierInput], cfg: RankConfig,
           max_suppliers: int = 2) -> Decision:
    """Choose who supplies what: one supplier, a split across at most two, or a partial fill."""
    by_name = {ln.name: ln for ln in lines}
    sups = {s.key: s for s in suppliers}
    timely = {k for k, s in sups.items() if meets_deadline(s, deadline, cfg)[0]}
    eligible: dict[str, list[str]] = {}
    for ln in lines:
        eligible[ln.name] = [k for k in timely if _usable_item(sups[k], ln)[0] is not None]

    coverable = [ln.name for ln in lines if eligible[ln.name]]
    uncovered = [ln.name for ln in lines if not eligible[ln.name]]
    if not coverable:
        return Decision("none", {}, [], uncovered=uncovered, note="no supplier can supply any item in time")

    best_single: tuple[float, float, dict, list] | None = None
    best_any: tuple[float, float, dict, list] | None = None
    for combo in itertools.product(*(eligible[i] for i in coverable)):
        assign = dict(zip(coverable, combo))
        used = set(combo)
        if len(used) > max_suppliers:
            continue
        total, expected, parts = assignment_cost(by_name, assign, sups, cfg)
        cand = (expected, total, assign, parts)
        if best_any is None or (cand[0], cand[1]) < (best_any[0], best_any[1]):
            best_any = cand
        if len(used) == 1 and (best_single is None or (cand[0], cand[1]) < (best_single[0], best_single[1])):
            best_single = cand

    assert best_any is not None  # coverable is non-empty and at least one supplier is eligible per item

    if uncovered:  # some item cannot be supplied at all: partial order, always needs the owner's yes
        e, t, a, p = best_any
        return Decision("partial", a, sorted(set(a.values())), t, e, uncovered, p,
                        note=f"cannot get {', '.join(uncovered)}")

    full_single = best_single if best_single and len(best_single[2]) == len(lines) else None
    if full_single is None:
        e, t, a, p = best_any
        return Decision("split" if len(set(a.values())) > 1 else "single", a, sorted(set(a.values())), t, e, [], p,
                        note="no single supplier can fill the whole order")

    se, st, sa, sp = full_single
    key = next(iter(sa.values()))
    ae, at, aa, ap = best_any
    used_any = set(aa.values())
    if len(used_any) > 1 and se - ae >= cfg.split_min_saving:
        return Decision("split", aa, sorted(used_any), at, ae, [], ap, single_best_key=key,
                        single_best_expected=round(se, 2), split_saving=round(se - ae, 2),
                        note=f"split saves Rs {se - ae:.0f} over the best single supplier")
    return Decision("single", sa, [key], st, se, [], sp, single_best_key=key, single_best_expected=round(se, 2),
                    split_saving=round(se - ae, 2) if len(used_any) > 1 else 0.0,
                    note="single supplier" if len(used_any) == 1 else
                    f"a split would save only Rs {se - ae:.0f}, below the Rs {cfg.split_min_saving:.0f} threshold")


def cash_total(parts: list[dict]) -> float:
    """What the owner actually pays: item subtotals plus delivery fees (credit is not cash saved)."""
    return round(sum(p["subtotal"] + (p.get("delivery_fee") or 0) for p in parts), 2)
