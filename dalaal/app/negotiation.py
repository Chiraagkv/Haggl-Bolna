"""Round-2 counter-offers (ticket #33). Pure functions.

THE RULE (Bible section 10, rule 2): a counter-offer may only cite a price that another supplier
really quoted. `assert_real_offers` re-checks that against the stored quotes right before any
round-2 call is placed, so a fabricated price cannot reach a prompt even through a bug.
"""

from __future__ import annotations

from dataclasses import dataclass

UNIT_WORDS = {"kg": "kilo", "litre": "litre", "piece": "piece"}


class FabricatedPriceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Offer:
    item: str
    their_price: float        # per base unit
    competing_price: float    # per base unit, another supplier's real quote
    from_supplier: str
    base_unit: str


def build_counter_offers(
    targets: list[str],
    confirmed: dict[str, dict[str, tuple[float, str]]],
) -> dict[str, list[Offer]]:
    """For each target supplier, the best REAL competing price per item, only where it is lower.

    `confirmed[supplier][item] = (price_per_base, base_unit)`. Never names another supplier to the
    supplier being called (the prompt only receives the number), but the source is kept for audit.
    """
    out: dict[str, list[Offer]] = {}
    for t in targets:
        offers: list[Offer] = []
        for item, (their, unit) in sorted(confirmed.get(t, {}).items()):
            rivals = [(p, k) for k, items in confirmed.items() if k != t
                      for it, (p, u) in items.items() if it == item and u == unit]
            if not rivals:
                continue
            best_price, best_key = min(rivals)
            if best_price < their:
                offers.append(Offer(item, their, best_price, best_key, unit))
        out[t] = offers
    return out


def assert_real_offers(offers: dict[str, list[Offer]], confirmed: dict[str, dict[str, tuple[float, str]]]) -> None:
    """Raise unless every competing price equals a stored quote of ANOTHER supplier."""
    for target, lst in offers.items():
        for o in lst:
            real = confirmed.get(o.from_supplier, {}).get(o.item)
            if o.from_supplier == target or real is None or real[0] != o.competing_price:
                raise FabricatedPriceError(
                    f"counter-offer for {target} cites {o.item} at {o.competing_price} "
                    f"from {o.from_supplier!r}, which is not a stored quote"
                )


@dataclass(frozen=True)
class Anchor:
    """The best REAL price another supplier has already confirmed for an item. A later round-1 wave
    hears it, so it can bargain live while the supplier is quoting (see orchestrator.plan_round1_waves)."""
    item: str
    price: float              # per base unit
    from_supplier: str
    base_unit: str


def build_anchors(target: str, items: list[str], confirmed: dict[str, dict[str, tuple[float, str]]]) -> list[Anchor]:
    """For each of `items`, the lowest confirmed price from a supplier other than `target`."""
    out: list[Anchor] = []
    for item in sorted(items):
        rivals = [(p, k, u) for k, quoted in confirmed.items() if k != target
                  for it, (p, u) in quoted.items() if it == item]
        if rivals:
            price, key, unit = min(rivals)
            out.append(Anchor(item, price, key, unit))
    return out


def assert_real_anchors(target: str, anchors: list[Anchor], confirmed: dict[str, dict[str, tuple[float, str]]]) -> None:
    """Same rule as assert_real_offers: every anchor must equal a stored quote of ANOTHER supplier."""
    for a in anchors:
        real = confirmed.get(a.from_supplier, {}).get(a.item)
        if a.from_supplier == target or real is None or real != (a.price, a.base_unit):
            raise FabricatedPriceError(
                f"anchor for {target} cites {a.item} at {a.price} from {a.from_supplier!r}, which is not a stored quote"
            )


def spoken_anchors(anchors: list[Anchor]) -> str:
    return ", ".join(f"{a.item} {number_text(a.price)} rupaye {UNIT_WORDS.get(a.base_unit, a.base_unit)}" for a in anchors)


def number_text(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


def spoken_counter(offers: list[Offer]) -> str:
    """'onions 25 rupaye kilo, oil 60 rupaye litre' -- numbers only, no supplier names."""
    return ", ".join(f"{o.item} {number_text(o.competing_price)} rupaye {UNIT_WORDS.get(o.base_unit, o.base_unit)}"
                     for o in offers)


def spoken_their_quote(offers: list[Offer]) -> str:
    return ", ".join(f"{o.item} {number_text(o.their_price)} rupaye {UNIT_WORDS.get(o.base_unit, o.base_unit)}"
                     for o in offers)
