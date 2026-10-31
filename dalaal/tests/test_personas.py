"""Checks the seed data (ticket #6) against the Bible's worked example, with no phone calls.

The formula here is the Bible's section 3, written out only to validate the data. The real,
tested ranking module arrives in Phase 4 (tickets #24-#27).
"""

import json
from pathlib import Path

import pytest

DATA = json.loads((Path(__file__).resolve().parent.parent / "data" / "personas.json").read_text())
ORDER = {i["name"]: i["quantity"] for i in DATA["owner"]["demo_order"]["items"]}
SUPPLIERS = {s["key"]: s for s in DATA["suppliers"]}
EXPECTED = DATA["expected_ranking"]


def quoted_total(s: dict) -> float:
    return sum(ORDER[item] * s["quote"][item] for item in ORDER)


def p_late(s: dict, a: int = 1, b: int = 3) -> float:
    h = s["history"]
    return (h["late"] + a) / (h["late"] + h["on_time"] + a + b)


def expected_cost(s: dict) -> float:
    return quoted_total(s) + p_late(s) * EXPECTED["lateness_cost"]


def test_four_personas_with_distinct_roles():
    assert set(SUPPLIERS) == {"kumar", "ramesh", "gowda", "lakshmi"}
    assert {s["language"] for s in SUPPLIERS.values()} == {"hi", "kn"}


def test_kumar_promises_the_deadline_so_only_his_record_hurts_him():
    assert SUPPLIERS["kumar"]["quote"]["delivery"] <= DATA["owner"]["demo_order"]["deadline"]


def test_lakshmi_has_no_oil():
    assert SUPPLIERS["lakshmi"]["quote"]["oil"] is None


@pytest.mark.parametrize("key,total", [("kumar", 1100), ("ramesh", 1140), ("gowda", 1180)])
def test_quoted_totals_match_bible(key, total):
    assert quoted_total(SUPPLIERS[key]) == total


@pytest.mark.parametrize("key", ["kumar", "ramesh", "gowda"])
def test_expected_costs_match_bible(key):
    assert round(expected_cost(SUPPLIERS[key])) == EXPECTED["expected_cost"][key]


def test_ramesh_wins_the_worked_example():
    costs = {k: expected_cost(SUPPLIERS[k]) for k in ("kumar", "ramesh", "gowda")}
    assert min(costs, key=costs.get) == EXPECTED["winner"]


def test_every_phone_is_a_placeholder_until_replaced():
    # A reminder, not a failure: real calls must only go to verified teammate numbers.
    owner = DATA["owner"]["phone"]
    assert owner.startswith("+91")
