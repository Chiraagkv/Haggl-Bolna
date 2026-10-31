"""How a call's outcome is decided. Regression for the live order of 2026-10-30, where the supplier said
"yes" twice, hung up after "thank you", and the booking was wrongly failed because Bolna's extractor
answered `confirmed` in a sentence instead of JSON."""

import pytest

from app import orchestrator as orc, services
from app.config import Settings
from app.models import Call, Order

S = Settings(_env_file=None)
ITEMS = [{"name": "oil", "quantity": 10, "unit": "litre"}, {"name": "onions", "quantity": 20, "unit": "kg"}]


def ext(**answers):
    return {"Dalaal": {k: {"subjective": v, "objective": None, "confidence": 0.9} for k, v in answers.items()}}


def confirm_call(extracted, status="completed", expected_total=900):
    return Call(kind="confirm", status=status, extracted_data=extracted, user_data={"expected_total": expected_total})


ORDER = Order(items=ITEMS, deadline="07:00")


@pytest.mark.parametrize("text,want", [
    ("yes", True), ("Yes, the supplier confirmed 10 litres of oil and 20 kilos of onions.", True), ("haan ji", True),
    ("हाँ", True), ("YES.", True), ('{"decision": "yes"}', True), ("no", False), ("Nahi, stock khatam", False),
    ("not confirmed", False), ("unclear", None), ("", None), (None, None), (True, True), ({"confirmed": False}, False),
])
def test_yes_no_reads_words_sentences_and_json(text, want):
    import json
    value = text
    if isinstance(text, str) and text.startswith("{"):
        value = json.loads(text)
    assert services.yes_no(value) == want


def test_number_reads_digits_words_and_devanagari():
    assert services.number("900") == 900 and services.number("Rs 1,100 total") == 1100 and services.number("९००") == 900
    assert services.number("none") is None and services.number(None) is None


def test_the_real_failed_call_is_now_confirmed():
    # exactly what Bolna returned live (the old single question), and the callee hung up after "thank you"
    real = {"Dalaal": {"confirmed": {"objective": None, "confidence": 1.0, "subjective":
            "Yes, the supplier confirmed 10 litres of oil and 20 kilos of onions for a total of 900 rupees with delivery by 07:00."}}}
    assert orc.confirm_result(confirm_call(real), ORDER, ["oil", "onions"], S) == (True, "ok")


def test_new_answers_shape_confirms_and_checks_terms():
    ok = ext(confirmed="yes", confirm_changed="no", confirm_total="900", confirm_delivery_time="07:00")
    assert orc.confirm_result(confirm_call(ok), ORDER, ["oil", "onions"], S)[0]
    changed = ext(confirmed="yes", confirm_changed="yes, wanted 55 per litre", confirm_total="950")
    assert orc.confirm_result(confirm_call(changed), ORDER, ["oil", "onions"], S) == (False, "supplier changed a quantity, price or delivery time")
    wrong_total = ext(confirmed="yes", confirm_changed="no", confirm_total="1200")
    assert orc.confirm_result(confirm_call(wrong_total), ORDER, ["oil", "onions"], S)[1].startswith("total mismatch")
    no_total = ext(confirmed="yes", confirm_changed="no", confirm_total="0")
    assert orc.confirm_result(confirm_call(no_total), ORDER, ["oil", "onions"], S)[0]  # no total said is not a mismatch


def test_what_still_fails_a_booking():
    assert orc.confirm_result(confirm_call(ext(confirmed="no")), ORDER, ["oil"], S) == (False, "supplier said no")
    assert orc.confirm_result(confirm_call(ext(confirmed="unclear")), ORDER, ["oil"], S) == (False, "no clear yes from the supplier")
    assert orc.confirm_result(confirm_call({}), ORDER, ["oil"], S) == (False, "no clear yes from the supplier")  # hung up before any yes
    assert orc.confirm_result(confirm_call(None, status="no-answer"), ORDER, ["oil"], S) == (False, "call no-answer")
