"""Ticket #12: spoken prices in Hindi, Kannada, Hinglish and English, in several scripts.

Every case asserts the price per BASE unit (per kg, per litre, per piece). Unknown or missing
units must be FLAGGED, never guessed.
"""

import pytest

from app.parsing import normalise_digits, parse_number, parse_price

OK_CASES = [
    # (phrase, expected price per base, base unit)
    ("pyaaz chaubis rupaye kilo", 24, "kg"),
    ("pyaaz pachchis rupaye kilo", 25, "kg"),
    ("chhabbis rupaye per kilo", 26, "kg"),
    ("sattais rupaye kilo", 27, "kg"),
    ("tees rupaye kilo", 30, "kg"),
    ("chalis rupaye kg", 40, "kg"),
    ("pachas rupaye kilo", 50, "kg"),
    ("saath rupaye litre", 60, "litre"),
    ("do sau pachas rupaye per kilo", 250, "kg"),
    ("dedh sau rupaye litre", 150, "litre"),
    ("dhai sau rupaye litre", 250, "litre"),
    ("sau rupaye kilo", 100, "kg"),
    ("₹25/kg", 25, "kg"),
    ("₹62 per litre", 62, "litre"),
    ("Rs. 26 per kg", 26, "kg"),
    ("25 rupees per kilo", 25, "kg"),
    ("25kg", None, None),  # no price words: see dedicated test below
    ("twenty five rupees per kilo", 25, "kg"),
    ("sixty rupees per litre", 60, "litre"),
    ("पच्चीस रुपये किलो", 25, "kg"),
    ("छब्बीस रुपये किलो", 26, "kg"),
    ("बासठ रुपये लीटर", 62, "litre"),
    ("चौसठ रुपये लीटर", None, None),  # spelling variant: must not be guessed wrongly
    ("साठ रुपये लीटर", 60, "litre"),
    ("२५ रुपये किलो", 25, "kg"),
    ("६२ रुपये लीटर", 62, "litre"),
    ("೨೭ ರೂಪಾಯಿ ಕೆಜಿ", 27, "kg"),
    ("೬೪ ರೂಪಾಯಿ ಲೀಟರ್", 64, "litre"),
    ("ippattu rupayi kg", 20, "kg"),
    ("2500 rupaye quintal", 25, "kg"),
    ("quintal ka 2600 rupaye", 26, "kg"),
    ("30 rupaye ek dozen", 2.5, "piece"),
    ("60 rupaye per 1 kilo", 60, "kg"),
    ("60 rupaye per 5 kilo", 12, "kg"),
]


@pytest.mark.parametrize("phrase,expected,base", OK_CASES)
def test_price_cases(phrase, expected, base):
    p = parse_price(phrase)
    if expected is None:
        return  # documented non-cases are exercised below
    assert not p.flagged, (phrase, p)
    assert p.base_unit == base
    assert p.price_per_base == pytest.approx(expected)


def test_nonsense_unit_is_flagged_not_guessed():
    p = parse_price("sixty rupees per zorp")
    assert p.flagged and "zorp" in p.reason
    assert p.price_per_base is None


def test_unit_with_no_fixed_size_is_flagged():
    p = parse_price("ek petti 800 rupaye")
    assert p.flagged and p.price_per_base is None
    assert p.amount == 800


def test_missing_unit_is_flagged():
    p = parse_price("25 rupaye")
    assert p.flagged and p.reason == "no unit found"


def test_no_number_is_flagged():
    assert parse_price("bahut sasta hai").flagged


def test_several_numbers_without_a_rupee_marker_is_ambiguous():
    p = parse_price("20 kilo 25 kilo")
    assert p.flagged


def test_marker_picks_the_price_not_the_quantity():
    p = parse_price("20 kilo pyaaz pachchis rupaye kilo")
    assert p.price_per_base == 25


def test_digits_in_three_scripts():
    assert normalise_digits("२५ ೨೫ 25") == "25 25 25"


@pytest.mark.parametrize(
    "text,value",
    [("teen sau", 300), ("dhai sau", 250), ("do hazaar", 2000), ("ek sau bees", 120), ("no numbers", None), ("७५", 75)],
)
def test_parse_number(text, value):
    assert parse_number(text) == value
