"""Number and unit parsing for spoken prices (ticket #12).

Handles digits in Latin, Devanagari and Kannada scripts, spoken Hindi number words
(romanised and Devanagari, 0-100 plus sau/hazaar/dedh/dhai), and Kannada digits plus a few
romanised Kannada words. Anything it does not understand is FLAGGED, never guessed: a silent
wrong price becomes a wrong booking.

Known limits (say them out loud): Kannada number WORDS are only covered for 1-10 and the
round tens, because compounds like "ippattaidu" (25) merge words. Spelling variants of spoken
numbers are endless; unknown words return None and the quote is flagged for the owner.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_DEV = str.maketrans("०१२३४५६७८९", "0123456789")
_KAN = str.maketrans("೦೧೨೩೪೫೬೭೮೯", "0123456789")

_TOKEN_RE = re.compile(r"[0-9A-Za-z.ऀ-ॿಀ-೿₹/]+")


def normalise_digits(text: str) -> str:
    return text.translate(_DEV).translate(_KAN)


# ---------------------------------------------------------------- number words
_WORDS: dict[str, float] = {}


def _add(value: float, *words: str) -> None:
    for w in words:
        _WORDS[w.lower()] = value


# Romanised Hindi 0-100 (common spellings)
for _v, _ws in {
    0: ["shunya", "zero"],
    1: ["ek"], 2: ["do"], 3: ["teen", "tiin"], 4: ["char", "chaar"], 5: ["paanch", "panch"],
    6: ["chhe", "chhah", "chah", "chhai"], 7: ["saat"], 8: ["aath"],
    9: ["nau", "nao"], 10: ["das"], 11: ["gyarah", "gyaarah", "igyarah"],
    12: ["barah", "baarah"], 13: ["terah", "terha"], 14: ["chaudah", "chaudaha"],
    15: ["pandrah", "pandra"], 16: ["solah"], 17: ["satrah", "satra"],
    18: ["atharah", "athaarah", "athara"], 19: ["unnis", "unneis", "unnees"],
    20: ["bees"], 21: ["ikkis", "ekkis", "ikkees"], 22: ["baais", "bais", "baees"],
    23: ["teis", "teyis"], 24: ["chaubis", "chobis", "chaubees", "chaubeece"],
    25: ["pachchis", "pachis", "pacchis", "pachees", "pachhis", "paccheese"],
    26: ["chhabbis", "chhabis", "chabbis", "chhabbees"], 27: ["sattais", "sattaees", "satais"],
    28: ["atthais", "athais", "aththais", "atthaees"], 29: ["untis", "unatis", "unatees"],
    30: ["tis", "tees", "tiis", "teess"], 31: ["ikattis", "iktis"], 32: ["battis", "batis"],
    33: ["taintis", "tentis", "tainteess"], 34: ["chauntis", "chavtis"], 35: ["paintis", "paitis", "paintees"],
    36: ["chhattis", "chattis", "chhatis"], 37: ["saintis", "saitis"], 38: ["adtis", "artis", "adatis"],
    39: ["untalis", "unatalis"], 40: ["chalis", "chaalis", "chalees"], 41: ["iktalis", "iktaalis"],
    42: ["bayalis", "byalis", "bayaalis"], 43: ["taintalis", "tentalis"], 44: ["chauvalis", "chavalis", "chauwalis"],
    45: ["paintalis", "paitalis", "paintaalis"], 46: ["chhiyalis", "chhiyaalis", "chiyalis"],
    47: ["saintalis", "saitalis"], 48: ["adtalis", "artalis"], 49: ["unchas", "unanchas", "unchaas"],
    50: ["pachas", "pachaas", "pachass"], 51: ["ikyavan", "ikyavan", "ekyavan"], 52: ["bavan", "baavan"],
    53: ["trepan", "tirpan", "tirpan"], 54: ["chauvan", "chauwan"], 55: ["pachpan", "pachpann"],
    56: ["chhappan", "chappan", "chhapan"], 57: ["sattavan", "satavan"], 58: ["atthavan", "athavan"],
    59: ["unsath", "unasath"], 60: ["saath", "sath", "saadh"], 61: ["iksath", "ikasath"], 62: ["basath", "baasath"],
    63: ["tirsath", "tirasath"], 64: ["chausath", "chaunsath"], 65: ["painsath", "paisath"],
    66: ["chhiyasath", "chiyasath"], 67: ["sarsath", "sadsath"], 68: ["adsath", "arsath"],
    69: ["unhattar", "unahattar"], 70: ["sattar", "satar"], 71: ["ikhattar", "ikahattar"],
    72: ["bahattar", "bahatar"], 73: ["tihattar", "tihatar"], 74: ["chauhattar", "chauhatar"],
    75: ["pachhattar", "pachattar", "pachahattar"], 76: ["chhihattar", "chihattar"],
    77: ["sattahattar", "satahattar"], 78: ["athhattar", "athattar"], 79: ["unnasi", "unyasi"],
    80: ["assi", "ashi"], 81: ["ikyasi", "ekyasi"], 82: ["bayasi", "byasi"], 83: ["tirasi", "tirasi"],
    84: ["chaurasi", "chourasi"], 85: ["pachasi", "pachaasi"], 86: ["chhiyasi", "chiyasi"],
    87: ["sattasi", "satasi"], 88: ["atthasi", "athasi"], 89: ["nawasi", "navasi"],
    90: ["nabbe", "nabbay", "nabbe"], 91: ["ikyanve", "ekyanve"], 92: ["baanve", "banve"],
    93: ["tiranve", "tiranave"], 94: ["chauranve", "chauranave"], 95: ["pachanve", "pachaanve"],
    96: ["chhiyanve", "chiyanve"], 97: ["sattanve", "satanve"], 98: ["atthanve", "athanve"],
    99: ["ninyanve", "ninanve", "ninnanve"],
}.items():
    _add(_v, *_ws)

# English number words (the transcriber sometimes returns English)
for _v, _w in enumerate(["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
                         "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
                         "nineteen"], start=1):
    _add(_v, _w)
for _v, _w in {20: "twenty", 30: "thirty", 40: "forty", 50: "fifty", 60: "sixty", 70: "seventy", 80: "eighty",
               90: "ninety"}.items():
    _add(_v, _w)

# "tis"/"tees" collide (3 vs 30 vs 23); keep the safest reading.
_WORDS["tees"] = 30

# Devanagari Hindi (spellings I am confident in)
for _v, _ws in {
    0: ["शून्य"], 1: ["एक"], 2: ["दो"], 3: ["तीन"], 4: ["चार"], 5: ["पांच", "पाँच"], 6: ["छह", "छः", "छे"],
    7: ["सात"], 8: ["आठ"], 9: ["नौ"], 10: ["दस"], 11: ["ग्यारह"], 12: ["बारह"], 13: ["तेरह"], 14: ["चौदह"],
    15: ["पंद्रह", "पन्द्रह"], 16: ["सोलह"], 17: ["सत्रह"], 18: ["अठारह"], 19: ["उन्नीस"], 20: ["बीस"],
    21: ["इक्कीस"], 22: ["बाईस"], 23: ["तेईस"], 24: ["चौबीस"], 25: ["पच्चीस"], 26: ["छब्बीस"],
    27: ["सत्ताईस"], 28: ["अट्ठाईस", "अठाईस"], 29: ["उनतीस"], 30: ["तीस"], 31: ["इकतीस"], 32: ["बत्तीस"],
    33: ["तैंतीस"], 34: ["चौंतीस"], 35: ["पैंतीस"], 36: ["छत्तीस"], 37: ["सैंतीस"], 38: ["अड़तीस"],
    39: ["उनतालीस"], 40: ["चालीस"], 41: ["इकतालीस"], 42: ["बयालीस"], 43: ["तैंतालीस"],
    44: ["चौवालीस", "चवालीस"], 45: ["पैंतालीस"], 46: ["छियालीस"], 47: ["सैंतालीस"], 48: ["अड़तालीस"],
    49: ["उनचास"], 50: ["पचास"], 51: ["इक्यावन"], 52: ["बावन"], 53: ["तिरपन"], 54: ["चौवन"],
    55: ["पचपन"], 56: ["छप्पन"], 57: ["सत्तावन"], 58: ["अट्ठावन"], 59: ["उनसठ"], 60: ["साठ"],
    61: ["इकसठ"], 62: ["बासठ"], 63: ["तिरसठ"], 64: ["चौंसठ"], 65: ["पैंसठ"], 66: ["छियासठ"],
    67: ["सड़सठ"], 68: ["अड़सठ"], 69: ["उनहत्तर"], 70: ["सत्तर"], 71: ["इकहत्तर"], 72: ["बहत्तर"],
    73: ["तिहत्तर"], 74: ["चौहत्तर"], 75: ["पचहत्तर"], 76: ["छिहत्तर"], 77: ["सतहत्तर"],
    78: ["अठहत्तर"], 79: ["उन्यासी"], 80: ["अस्सी"], 81: ["इक्यासी"], 82: ["बयासी"], 83: ["तिरासी"],
    84: ["चौरासी"], 85: ["पचासी"], 86: ["छियासी"], 87: ["सत्तासी"], 88: ["अट्ठासी"], 89: ["नवासी"],
    90: ["नब्बे"], 91: ["इक्यानबे"], 92: ["बानवे"], 93: ["तिरानवे"], 94: ["चौरानवे"], 95: ["पंचानवे"],
    96: ["छियानवे"], 97: ["सत्तानवे"], 98: ["अट्ठानवे"], 99: ["निन्यानवे"],
}.items():
    _add(_v, *_ws)

# Kannada: digits are handled above; words only 1-10 and round tens (romanised + script)
for _v, _ws in {
    1: ["ondu", "ಒಂದು"], 2: ["eradu", "ಎರಡು"], 3: ["mooru", "muru", "ಮೂರು"], 4: ["naalku", "nalku", "ನಾಲ್ಕು"],
    5: ["aidu", "ಐದು"], 6: ["aaru", "ಆರು"], 7: ["elu", "ಏಳು"], 8: ["entu", "ಎಂಟು"],
    9: ["ombattu", "ombhattu", "ಒಂಬತ್ತು"], 10: ["hattu", "ಹತ್ತು"], 20: ["ippattu", "ಇಪ್ಪತ್ತು"],
    30: ["muvattu", "ಮೂವತ್ತು"], 40: ["naalvattu", "ನಲವತ್ತು"], 50: ["aivattu", "ಐವತ್ತು"],
    60: ["aravattu", "ಅರವತ್ತು"], 70: ["eppattu", "ಎಪ್ಪತ್ತು"], 80: ["embhattu", "ಎಂಬತ್ತು"],
    90: ["tombattu", "ತೊಂಬತ್ತು"],
}.items():
    _add(_v, *_ws)

_HUNDRED = {"sau", "सौ", "nooru", "ನೂರು", "hundred"}
_THOUSAND = {"hazaar", "hazar", "hajar", "haazar", "हज़ार", "हजार", "saavira", "ಸಾವಿರ", "thousand"}
_HALF_FORMS = {"dedh": 1.5, "डेढ़": 1.5, "dhai": 2.5, "dhaai": 2.5, "ढाई": 2.5}

_NUM_RE = re.compile(r"^\d+(\.\d+)?$")


def _is_numtoken(tok: str) -> bool:
    t = tok.lower()
    return bool(_NUM_RE.match(t)) or t in _WORDS or t in _HUNDRED or t in _THOUSAND or t in _HALF_FORMS


def _tokens(text: str) -> list[str]:
    toks = (t.strip(".") for t in _TOKEN_RE.findall(normalise_digits(text)))
    return [t for t in toks if t]


def _collect(tokens: list[str], i: int) -> tuple[float | None, int]:
    """Read one number expression starting at tokens[i]; return (value, next_index)."""
    total = 0.0
    current: float | None = None
    j = i
    seen = False
    while j < len(tokens) and _is_numtoken(tokens[j]):
        t = tokens[j].lower()
        if t in _HUNDRED:
            total += (current if current is not None else 1) * 100
            current = None
        elif t in _THOUSAND:
            total += (current if current is not None else 1) * 1000
            current = None
        else:
            if _NUM_RE.match(t):
                val = float(t)
            elif t in _HALF_FORMS:
                val = _HALF_FORMS[t]
            else:
                val = _WORDS[t]
            if current is not None:
                if current % 10 == 0 and 20 <= current <= 90 and 1 <= val <= 9:
                    current += val  # "twenty five"
                    seen = True
                    j += 1
                    continue
                break  # two small numbers in a row: a new expression starts here
            current = val
        seen = True
        j += 1
    if not seen:
        return None, i
    return total + (current or 0), j


def parse_number(text: str) -> float | None:
    """First number in the text, or None."""
    toks = _tokens(text)
    i = 0
    while i < len(toks):
        val, nxt = _collect(toks, i)
        if val is not None:
            return val
        i += 1
    return None


# ----------------------------------------------------------------------- units
@dataclass(frozen=True)
class UnitInfo:
    canonical: str            # e.g. "kg", "quintal"
    base: str | None          # "kg", "litre", "piece", or None when size unknown
    to_base: float | None     # multiply quantity by this to get base units


_UNITS: dict[str, UnitInfo] = {}


def _unit(canonical: str, base: str | None, to_base: float | None, *words: str) -> None:
    info = UnitInfo(canonical, base, to_base)
    for w in words:
        _UNITS[w.lower()] = info


_unit("kg", "kg", 1, "kg", "kgs", "kilo", "kilos", "kilogram", "kilograms", "किलो", "किलोग्राम", "किग्रा", "केजी",
      "ಕೆಜಿ", "ಕಿಲೋ", "kgm")
_unit("quintal", "kg", 100, "quintal", "qtl", "quintals", "क्विंटल", "ಕ್ವಿಂಟಾಲ್")
_unit("gram", "kg", 0.001, "gram", "grams", "gm", "ग्राम", "ಗ್ರಾಂ")
_unit("litre", "litre", 1, "litre", "liter", "litres", "liters", "ltr", "lit", "लीटर", "लिटर", "ಲೀಟರ್")
_unit("ml", "litre", 0.001, "ml", "मिलीलीटर", "ಮಿಲಿ")
_unit("piece", "piece", 1, "piece", "pieces", "pc", "pcs", "nag", "नग", "पीस")
_unit("dozen", "piece", 12, "dozen", "darjan", "दर्जन")
# Units whose size is not fixed: refuse to convert, flag for the owner.
for _w in ["petti", "पेटी", "box", "crate", "tin", "dabba", "डब्बा", "bori", "bora", "bag", "बोरी", "बोरा", "packet"]:
    _UNITS[_w] = UnitInfo(_w, None, None)

_PER_WORDS = {"per", "/", "prati", "प्रति", "ka", "ke", "ki", "का", "के", "की", "ಒಂದು", "pratee"}
_RUPEE_MARKERS = {"₹", "rs", "rs.", "inr", "rupaye", "rupee", "rupees", "rupya", "rupiya", "rupay", "रुपये", "रुपए",
                  "रुपया", "रु", "रु.", "ರೂಪಾಯಿ", "ರೂ", "rupayi", "rupaayi", "rooppaayi"}


def normalise_unit(text: str) -> UnitInfo | None:
    """Look up one unit word. Returns None if it is not a known unit."""
    return _UNITS.get(text.strip().lower().rstrip(".,"))


@dataclass
class ParsedPrice:
    amount: float | None
    unit: str | None
    base_unit: str | None
    price_per_base: float | None
    flagged: bool
    reason: str | None = None


def _split_attached(tok: str) -> list[str]:
    """'₹25/kg' -> ['₹', '25', '/', 'kg'] so markers and units are seen."""
    out: list[str] = []
    buf = ""
    for ch in tok:
        if ch in "₹/":
            if buf:
                out.append(buf)
                buf = ""
            out.append(ch)
        else:
            buf += ch
    if buf:
        out.append(buf)
    # '25kg' -> '25', 'kg'
    final: list[str] = []
    for p in out:
        m = re.match(r"^(\d+(?:\.\d+)?)([A-Za-z]+)$", p)
        final.extend([m.group(1), m.group(2)] if m else [p])
    return final


def parse_price(text: str) -> ParsedPrice:
    """Parse a spoken or typed price such as 'pyaaz chaubis rupaye kilo' or '₹25/kg'.

    Returns the price normalised to a base unit (per kg, per litre, per piece) where possible.
    If the unit is missing or unknown the result is flagged and price_per_base is None.
    """
    toks: list[str] = []
    for t in _tokens(text):
        toks.extend(_split_attached(t))
    toks = [t for t in toks if t]

    # all number expressions with their positions
    spans: list[tuple[float, int, int]] = []
    i = 0
    while i < len(toks):
        val, nxt = _collect(toks, i)
        if val is not None:
            spans.append((val, i, nxt))
            i = nxt
        else:
            i += 1

    if not spans:
        return ParsedPrice(None, None, None, None, True, "no number found")

    marker_idx = [k for k, t in enumerate(toks) if t.lower() in _RUPEE_MARKERS]
    chosen = spans[0]
    if marker_idx:
        best = None
        for span in spans:
            for m in marker_idx:
                # prefer a number right before the marker, then right after it
                if span[2] == m:
                    dist = 0
                elif span[1] == m + 1:
                    dist = 1
                else:
                    dist = 2 + min(abs(span[1] - m), abs(span[2] - m))
                if best is None or dist < best[0]:
                    best = (dist, span)
        chosen = best[1]  # type: ignore[index]
    elif len(spans) > 1:
        return ParsedPrice(spans[0][0], None, None, None, True, "several numbers and no rupee marker: ambiguous")

    amount, start, end = chosen

    # unit: look just after the amount (skipping rupee and 'per' words), then anywhere before.
    # A number between 'per' and the unit is a quantity: "60 rupaye per 5 kilo" is 12 per kg.
    unit: UnitInfo | None = None
    unknown_word: str | None = None
    qty = 1.0
    after = toks[end:]
    k = 0
    while k < len(after):
        tl = after[k].lower()
        if tl in _RUPEE_MARKERS or tl in _PER_WORDS:
            k += 1
            continue
        if _is_numtoken(tl):
            val, nxt = _collect(after, k)
            if val is not None and val > 0:
                qty = val
                k = nxt
                continue
        u = normalise_unit(tl)
        if u:
            unit = u
            break
        if k > 0 and after[k - 1].lower() in _PER_WORDS:
            unknown_word = tl
            break
        k += 1
    if unit is None and unknown_word is None:
        qty = 1.0
        # unit may have been said before the amount ("kilo ka pachchis rupaye")
        for t in toks[:start]:
            u = normalise_unit(t)
            if u:
                unit = u
                break

    if unit is None:
        reason = f"unknown unit '{unknown_word}'" if unknown_word else "no unit found"
        return ParsedPrice(amount, None, None, None, True, reason)
    if unit.base is None or unit.to_base is None:
        return ParsedPrice(amount, unit.canonical, None, None, True, f"unit '{unit.canonical}' has no fixed size")
    return ParsedPrice(amount, unit.canonical, unit.base, round(amount / (unit.to_base * qty), 4), False)
