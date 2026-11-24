from decimal import Decimal

import pytest

from tracker.core.units import (
    GRAMS_PER_UNIT,
    Unit,
    parse_bn_number,
    price_per_gram,
    price_per_unit,
    to_grams,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("৳১,৯৮,১১৩", Decimal("198113")),  # goldr per-bhori 22K, Indian grouping
        ("৳১৬,৯৮৫", Decimal("16985")),  # goldr per-gram 22K
        ("১৬৯৮৫.৫০", Decimal("16985.50")),
        ("  ৳ ১,২৩৪ ", Decimal("1234")),
        ("৳ ১,২৩৪", Decimal("1234")),  # non-breaking space from HTML &nbsp;
        ("198,113", Decimal("198113")),  # Latin digits pass through
    ],
)
def test_parse_bn_number(text: str, expected: Decimal) -> None:
    assert parse_bn_number(text) == expected


@pytest.mark.parametrize("text", ["", "৳", " , ", "দাম", "১২a", "NaN", "Infinity"])
def test_parse_bn_number_rejects_non_numbers(text: str) -> None:
    with pytest.raises(ValueError):
        parse_bn_number(text)


def test_unit_relations_match_the_spec() -> None:
    assert GRAMS_PER_UNIT[Unit.ANA] * 16 == GRAMS_PER_UNIT[Unit.BHORI]
    assert GRAMS_PER_UNIT[Unit.RATI] * 6 == GRAMS_PER_UNIT[Unit.ANA]


def test_goldr_sanity_check_from_spec() -> None:
    # Spec §5: 22K = ৳16,985/g and ৳1,98,113/bhori on 23 Nov 2026.
    per_bhori = price_per_unit(Decimal("16985"), Unit.BHORI)
    assert per_bhori.quantize(Decimal("1")) == Decimal("198113")
    assert price_per_gram(Decimal("198113"), Unit.BHORI).quantize(Decimal("1")) == 16985


def test_round_trip_and_grams() -> None:
    price = Decimal("12345.67")
    for unit in Unit:
        assert price_per_gram(price_per_unit(price, unit), unit) == price
    assert to_grams(Decimal("2"), Unit.TROY_OUNCE) == Decimal("62.2070")
