import json
import pytest
from app import ranking as rk, savings as sv, negotiation as ng
from app.seed import load_personas

CFG = rk.RankConfig()
LINES = rk.order_lines([{"name": "onions", "quantity": 20, "unit": "kg"}, {"name": "oil", "quantity": 10, "unit": "litre"}])


def sups(overrides=None, drop=()):
    out = []
    for s in load_personas()["suppliers"]:
        if s["key"] in drop:
            continue
        q = {}
        for item, v in s["quote"].items():
            if item in ("delivery", "credit_days", "delivery_fee"):
                continue
            if v is not None:
                q[item] = rk.ItemQuote(float(v), "kg" if item == "onions" else "litre")
        out.append(rk.SupplierInput(s["key"], s["name"], q, s["quote"]["delivery"], s["quote"].get("credit_days") or 0,
                                    s["quote"].get("delivery_fee") or 0, s["history"]["on_time"], s["history"]["late"]))
    for s in out:
        for k, f in (overrides or {}).get(s.key, {}).items():
            f(s) if callable(f) else setattr(s, k, f)
    return out


def test_worked_example():
    r = rk.rank_suppliers(LINES, "07:00", sups(drop=("lakshmi",)), CFG)
    got = {x.key: round(x.expected_cost) for x in r.ranked}
    assert got == {"kumar": 1229, "ramesh": 1183, "gowda": 1244}
    assert r.ranked[0].key == "ramesh"


def test_kumar_wins_if_100_cheaper():
    s = sups(drop=("lakshmi",))
    k = next(x for x in s if x.key == "kumar")
    k.quotes["onions"].price_per_base -= 5  # 20kg * 5 = 100
    assert rk.rank_suppliers(LINES, "07:00", s, CFG).ranked[0].key == "kumar"


def test_deadline_filter_and_missing_time():
    s = sups(drop=("lakshmi",))
    s[0].delivery_time = "07:30"
    r = rk.rank_suppliers(LINES, "07:00", s, CFG)
    assert [i.key for i in r.infeasible] == ["kumar"]
    s[1].delivery_time = None
    assert "ramesh" in [i.key for i in rk.rank_suppliers(LINES, "07:00", s, CFG).infeasible]


def test_split_basket_lakshmi():
    s = sups()
    next(x for x in s if x.key == "lakshmi").quotes["onions"].price_per_base = 22  # the split_variant price
    d = rk.decide(LINES, "07:00", s, CFG)
    assert d.kind == "split"
    assert d.assignments == {"onions": "lakshmi", "oil": "ramesh"}
    assert d.split_saving >= 60 and round(d.expected_cost) < 1183


def test_split_not_used_below_threshold():
    s = sups()
    next(x for x in s if x.key == "lakshmi").quotes["onions"].price_per_base = 22
    d = rk.decide(LINES, "07:00", s, rk.RankConfig(split_min_saving=500))
    assert d.kind == "single" and d.suppliers == ["ramesh"]


def test_partial_when_item_unavailable():
    s = sups(drop=("lakshmi",))
    for x in s:
        x.quotes.pop("oil")
    d = rk.decide(LINES, "07:00", s, CFG)
    assert d.kind == "partial" and d.uncovered == ["oil"]


def test_none():
    assert rk.decide(LINES, "05:00", sups(), CFG).kind == "none"


def test_clock_parsing():
    assert rk.parse_clock("07:00") == 420 and rk.parse_clock("6.30 am") == 390
    assert rk.parse_clock("7 pm") == 1140 and rk.parse_clock("x") is None and rk.parse_clock("25:00") is None


def test_ranked_lower_note():
    r = rk.rank_suppliers(LINES, "07:00", sups(drop=("lakshmi",)), CFG)
    n = rk.ranked_lower_note(r.ranked)
    assert n["key"] == "kumar" and "late 2 of last 3" in n["text"]


def test_savings_baseline_and_never_negative():
    b = sv.baseline(LINES, load_personas()["owner"]["usual_prices"], 1300)
    assert b.kind == "owner_last_paid_price" and b.total == 1300.0
    assert sv.savings(b.total, 1140) == {"savings": 160.0, "raw": 160.0}
    assert sv.savings(1000, 1100) == {"savings": 0.0, "raw": -100.0}
    assert sv.baseline(LINES, {"onions": {"price": 30, "unit": "kg"}}, 1250).kind == "usual_supplier_quote"
    assert sv.baseline(LINES, None, None) is None and sv.savings(None, 1)["savings"] is None


def test_counter_offers_real_only():
    conf = {"kumar": {"onions": (25, "kg"), "oil": (60, "litre")}, "ramesh": {"onions": (26, "kg"), "oil": (62, "litre")},
            "gowda": {"onions": (27, "kg"), "oil": (64, "litre")}}
    offers = ng.build_counter_offers(["ramesh"], conf)
    assert [(o.item, o.competing_price) for o in offers["ramesh"]] == [("oil", 60), ("onions", 25)]
    ng.assert_real_offers(offers, conf)
    bad = {"ramesh": [ng.Offer("onions", 26, 20, "kumar", "kg")]}
    with pytest.raises(ng.FabricatedPriceError):
        ng.assert_real_offers(bad, conf)
    assert ng.build_counter_offers(["kumar"], conf)["kumar"] == []
    assert "25 rupaye kilo" in ng.spoken_counter(offers["ramesh"])


def test_mandi_flag():
    from app import reference
    t = {"onions": {"unit": "kg", "low": 18, "high": 38}}
    assert reference.check("onions", 25, "kg", t) is None
    assert "above" in reference.check("onions", 60, "kg", t)
    assert "below" in reference.check("onions", 5, "kg", t)
    assert reference.check("saffron", 5000, "kg", t) is None and reference.check("onions", 25, "litre", t) is None
