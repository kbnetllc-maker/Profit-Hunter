"""Inbound shipping for seller bundles.

Four different numbers are kept apart:

* actual shipping paid          - real charges already made (sunk cost)
* estimated pending shipping    - expected charges on unsettled purchases
* incremental shipping          - what the NEXT item would add (used for
                                  the buying decision)
* allocated shipping            - a bundle's total shipping split across
                                  its items (used for inventory cost)
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..money import CENT, ZERO, round_cents


@dataclass(frozen=True)
class ShippingTerms:
    """A seller's shipping terms. None means 'not known'."""

    first_item_shipping: Decimal | None = None
    additional_item_shipping: Decimal | None = None
    shipping_cap: Decimal | None = None  # most the whole bundle can cost


@dataclass(frozen=True)
class BundleState:
    """The open bundle with this seller, if any."""

    is_open: bool = False
    item_count: int = 0
    actual_shipping_paid: Decimal = ZERO
    estimated_shipping_pending: Decimal = ZERO

    @property
    def shipping_so_far(self) -> Decimal:
        return self.actual_shipping_paid + self.estimated_shipping_pending


@dataclass(frozen=True)
class ShippingEstimate:
    amount: Decimal
    is_estimate: bool  # True = conservative guess; ask the seller to verify
    basis: str


def incremental_shipping(terms: ShippingTerms, bundle: BundleState, *,
                         unknown_first_item_estimate: Decimal,
                         unknown_additional_item_estimate: Decimal) -> ShippingEstimate:
    """Shipping the next purchase would add. Never assumes extra items ship free."""
    in_bundle = bundle.is_open and bundle.item_count > 0
    if not in_bundle:  # no bundle, or the previous bundle closed: a new shipment starts
        if terms.first_item_shipping is not None:
            amount, est, basis = terms.first_item_shipping, False, "Seller's first-item shipping rate"
        else:
            amount, est, basis = (unknown_first_item_estimate, True,
                                  "First-item shipping unknown: conservative default estimate")
        so_far = ZERO
    else:
        if terms.additional_item_shipping is not None:
            amount, est, basis = (terms.additional_item_shipping, False,
                                  "Seller's additional-item shipping rate (open bundle)")
        else:
            amount, est, basis = (unknown_additional_item_estimate, True,
                                  "Additional-item shipping unknown: conservative default "
                                  "estimate. Verify with the seller")
        so_far = bundle.shipping_so_far

    if terms.shipping_cap is not None:
        room = max(terms.shipping_cap - so_far, ZERO)
        if amount > room:
            amount = room
            est = False  # the cap is a known upper bound
            basis = (f"Bundle shipping cap ${terms.shipping_cap:.2f} reached "
                     f"(${so_far:.2f} already counted)")
    return ShippingEstimate(round_cents(amount), est, basis)


def allocate(total: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """Split ``total`` across items in proportion to ``weights``, exact to the cent.

    Equal weights give an equal split. The pieces always add up to ``total``.
    """
    total = round_cents(total)
    if not weights:
        if total != 0:
            raise ValueError("Cannot allocate a non-zero amount across zero items.")
        return []
    if any(w < 0 for w in weights):
        raise ValueError("Weights must not be negative.")
    weight_sum = sum(weights, Decimal(0))
    if weight_sum == 0:
        weights, weight_sum = [Decimal(1)] * len(weights), Decimal(len(weights))
    cents = int(total * 100)
    raw = [Decimal(cents) * w / weight_sum for w in weights]
    floors = [int(r) for r in raw]
    leftover = cents - sum(floors)
    # Hand leftover cents to the largest remainders (earliest item wins ties).
    order = sorted(range(len(raw)), key=lambda k: (-(raw[k] - floors[k]), k))
    for k in order[:leftover]:
        floors[k] += 1
    return [Decimal(f) * CENT for f in floors]
