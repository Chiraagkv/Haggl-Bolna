"""Round 1 in waves: suppliers grouped by what they sell, dialed a pair at a time, later waves anchored."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app import negotiation, orchestrator as orc, orders, seed
from app.models import Call, Order, Supplier


def sup(id_, key, items):
    return Supplier(id=id_, owner_id=1, key=key, name=key, items=items)


def keys(waves):
    return [[x.key for x in w] for w in waves]


def test_pairs_group_suppliers_who_sell_the_same_items():
    sups = [sup(1, "a", ["onions"]), sup(2, "b", ["oil"]), sup(3, "c", ["onions"]), sup(4, "d", ["oil"])]
    assert keys(orc.plan_round1_waves({"onions", "oil"}, sups, 2)) == [["a", "c"], ["b", "d"]]


def test_identical_baskets_pair_first():
    sups = [sup(1, "kumar", ["onions", "oil"]), sup(2, "lakshmi", ["onions"]), sup(3, "ramesh", ["onions", "oil"])]
    assert keys(orc.plan_round1_waves({"onions", "oil"}, sups, 2)) == [["kumar", "ramesh"], ["lakshmi"]]


def test_loners_share_a_wave_and_nobody_is_dropped():
    sups = [sup(1, "a", ["onions"]), sup(2, "b", ["oil"]), sup(3, "c", ["rice"])]
    waves = orc.plan_round1_waves({"onions", "oil", "rice"}, sups, 2)
    assert sorted(k for w in keys(waves) for k in w) == ["a", "b", "c"]
    assert all(len(w) <= 2 for w in waves)


def test_bigger_concurrency_means_bigger_waves():
    sups = [sup(i, f"s{i}", ["onions"]) for i in range(1, 6)]
    assert [len(w) for w in orc.plan_round1_waves({"onions"}, sups, 10)] == [5]


def make(session, owner):
    spec = seed.demo_order_spec()
    return orc.create_order(session, owner.id, spec["items"], spec["deadline"], spec["budget"])


def test_demo_round1_runs_in_two_pairs_and_second_wave_is_anchored(session, world, fake):
    o = make(session, world)
    assert orc.start_order(session, o.id)
    orc.run_until_idle(session, fake)
    r1 = [c for c in fake.placed if c.kind == "supplier_r1"]
    assert [c.user_data["wave"] for c in r1] == [0, 0, 1, 1]  # wave 1 only after wave 0 finished
    assert {c.user_data["supplier_key"] for c in r1[:2]} == {"kumar", "ramesh"}
    assert r1[0].user_data["competing_quote_spoken"] == "none"
    gowda = next(c for c in r1 if c.user_data["supplier_key"] == "gowda")
    assert gowda.user_data["anchors"] == [{"item": "oil", "price": 60.0, "unit": "litre"},
                                          {"item": "onions", "price": 25.0, "unit": "kg"}]  # Kumar's real, confirmed quote
    lakshmi = next(c for c in r1 if c.user_data["supplier_key"] == "lakshmi")
    assert [a["item"] for a in lakshmi.user_data["anchors"]] == ["onions"]  # only what she sells
    session.expire_all()
    assert session.get(Order, o.id).state == orders.REPORTED


def test_round1_deadline_covers_every_wave(session, world, fake, set_env):
    set_env(ROUND1_DEADLINE_SECONDS=100)
    o = make(session, world)
    assert orc.start_order(session, o.id)
    session.refresh(o)
    assert orc.aware(o.r1_deadline_at) - orc.aware(o.r1_started_at) == timedelta(seconds=200)  # two waves


def test_stuck_wave_does_not_block_the_next_one_forever(session, world, fake, set_env):
    fake.behaviour["kumar"] = "hang"
    o = make(session, world)
    assert orc.start_order(session, o.id)
    orc.tick(session, fake)
    fake.pump(session, force=True)
    orc.tick(session, fake)
    later = [c for c in session.scalars(select(Call).where(Call.order_id == o.id, Call.kind == "supplier_r1"))
             if c.user_data["wave"] == 1]
    assert all(c.status == "pending" for c in later)  # Kumar is still on the line
    s = orc.get_settings()
    orc.tick(session, fake, now=orc.now_utc() + timedelta(seconds=s.round1_deadline_seconds + 1))
    session.expire_all()
    assert any(c.status != "pending" for c in session.scalars(select(Call).where(Call.order_id == o.id, Call.kind == "supplier_r1"))
               if c.user_data["wave"] == 1)


def test_anchor_never_cites_the_supplier_itself_or_an_unconfirmed_price():
    confirmed = {"kumar": {"onions": (25.0, "kg")}, "gowda": {"onions": (24.0, "kg")}}
    assert negotiation.build_anchors("gowda", ["onions"], confirmed) == [negotiation.Anchor("onions", 25.0, "kumar", "kg")]
    with pytest.raises(negotiation.FabricatedPriceError):
        negotiation.assert_real_anchors("gowda", [negotiation.Anchor("onions", 20.0, "kumar", "kg")], confirmed)
    with pytest.raises(negotiation.FabricatedPriceError):
        negotiation.assert_real_anchors("gowda", [negotiation.Anchor("onions", 24.0, "gowda", "kg")], confirmed)


class LowWallet:
    def wallet_inr(self):
        return 20.0


def test_order_refused_when_wallet_cannot_cover_it(session, world, fake):
    o = make(session, world)
    assert not orc.start_order(session, o.id, provider=LowWallet())
    session.refresh(o)
    assert o.state == orders.FAILED and o.failure_reason.startswith("wallet_too_low")
    assert not session.scalars(select(Call).where(Call.order_id == o.id)).all()
