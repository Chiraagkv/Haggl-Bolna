"""Fair-price flag (ticket #30). Compares a quote with a reference range and returns a short note.

It is a warning for the owner and the dashboard, never an input to ranking: a wrong reference table
must not be able to change who wins. Items with no reference are simply not checked.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "data" / "reference_prices.json"


@lru_cache
def load(path: str | None = None) -> dict:
    try:
        data = json.loads(Path(path or PATH).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {k: v for k, v in data.items() if not k.startswith("_") and isinstance(v, dict)}


def check(item: str, per_base: float | None, base_unit: str | None, table: dict | None = None) -> str | None:
    if per_base is None:
        return None
    ref = (table if table is not None else load()).get(item.strip().lower())
    if not ref or ref.get("unit") != base_unit:
        return None
    if per_base > ref["high"]:
        return f"above the usual range ({ref['low']}-{ref['high']} per {base_unit})"
    if per_base < ref["low"]:
        return f"below the usual range ({ref['low']}-{ref['high']} per {base_unit}): check it is the same quality"
    return None
