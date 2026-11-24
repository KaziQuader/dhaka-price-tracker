"""Bengali numerals and Bangladeshi gold units (spec §5).

Prices are stored per gram. These helpers convert for parsing and display only.
Decimal is used throughout: float would turn ৳16,985 × 11.664 into 198113.03999999998.
"""

from decimal import Decimal, InvalidOperation
from enum import StrEnum

_BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
# Taka sign, thousands separators and every kind of space (incl. non-breaking) are dropped.
_STRIP = str.maketrans("", "", "৳,   \t\n")


def parse_bn_number(text: str) -> Decimal:
    """'৳১,৯৮,১১৩' -> Decimal('198113'). Also accepts Latin digits and a decimal point."""
    cleaned = text.translate(_BN_DIGITS).translate(_STRIP)
    if not cleaned:
        raise ValueError(f"no number in {text!r}")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"not a number: {text!r}") from None
    if not value.is_finite():
        raise ValueError(f"not a finite number: {text!r}")
    return value


class Unit(StrEnum):
    GRAM = "gram"
    BHORI = "bhori"  # also spelled vori
    ANA = "ana"
    RATI = "rati"
    TROY_OUNCE = "troy_ounce"


GRAMS_PER_UNIT: dict[Unit, Decimal] = {
    Unit.GRAM: Decimal("1"),
    Unit.BHORI: Decimal("11.664"),
    Unit.ANA: Decimal("0.729"),  # 1/16 bhori
    Unit.RATI: Decimal("0.1215"),  # 1/6 ana
    Unit.TROY_OUNCE: Decimal("31.1035"),
}


def to_grams(amount: Decimal, unit: Unit) -> Decimal:
    return amount * GRAMS_PER_UNIT[unit]


def price_per_gram(price: Decimal, unit: Unit) -> Decimal:
    """Price quoted per `unit` -> price per gram (e.g. per-bhori price / 11.664)."""
    return price / GRAMS_PER_UNIT[unit]


def price_per_unit(price_per_gram_: Decimal, unit: Unit) -> Decimal:
    """Price per gram -> price per `unit` (e.g. per-gram price × 11.664 for one bhori)."""
    return price_per_gram_ * GRAMS_PER_UNIT[unit]
