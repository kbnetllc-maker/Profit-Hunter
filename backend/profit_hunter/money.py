"""Money helpers.

All money in the calculation engine is a ``Decimal`` number of dollars.
The database stores whole cents as integers. Floats are rejected so that
binary rounding errors can never enter a financial calculation.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def D(value: Decimal | int | str) -> Decimal:
    """Convert to Decimal. Floats are refused on purpose."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError(
            f"Money must be given as Decimal, int or str, not {type(value).__name__}: {value!r}"
        )
    return Decimal(value)


def round_cents(value: Decimal | int | str) -> Decimal:
    """Round to whole cents (half rounds up)."""
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


def to_cents(value: Decimal | int | str) -> int:
    """Dollars -> integer cents for database storage."""
    return int(round_cents(value) * 100)


def from_cents(cents: int) -> Decimal:
    """Integer cents from the database -> dollars."""
    return (Decimal(cents) / 100).quantize(CENT)


def opt_to_cents(value: Decimal | int | str | None) -> int | None:
    return None if value is None else to_cents(value)


def opt_from_cents(cents: int | None) -> Decimal | None:
    return None if cents is None else from_cents(cents)
