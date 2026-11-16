"""Acquisition cost, sale proceeds and profit calculations.

Vocabulary (kept strict so numbers are never confused):

* sale price        - what the buyer is expected to pay for the item.
                      This is the CONSERVATIVE EXPECTED SALE PRICE, not the
                      listing/asking price.
* net proceeds      - sale price minus every selling expense.
* all-in cost       - bid + incremental inbound shipping + purchase tax.
* net profit        - net proceeds minus all-in cost.
* ROI               - net profit / all-in cost. Never revenue / cost.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..config import FeeProfile
from ..money import ZERO, D, round_cents


# --------------------------------------------------------------------------
# Buying side
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class PurchaseTerms:
    """Costs on top of the bid for the NEXT purchase.

    ``inbound_shipping`` is the INCREMENTAL shipping this purchase adds.
    Shipping already paid to the seller is a sunk cost and must not be
    included here.
    """

    inbound_shipping: Decimal = ZERO
    tax_rate: Decimal = ZERO
    tax_applies_to_shipping: bool = True


@dataclass(frozen=True)
class AcquisitionCost:
    bid: Decimal
    inbound_shipping: Decimal
    purchase_tax: Decimal
    total: Decimal  # the all-in acquisition cost


def acquisition_cost(bid: Decimal, terms: PurchaseTerms) -> AcquisitionCost:
    bid = round_cents(bid)
    shipping = round_cents(terms.inbound_shipping)
    if bid < 0 or shipping < 0 or terms.tax_rate < 0:
        raise ValueError("Bid, shipping and tax rate must not be negative.")
    taxable = bid + (shipping if terms.tax_applies_to_shipping else ZERO)
    tax = round_cents(taxable * D(terms.tax_rate))
    return AcquisitionCost(bid=bid, inbound_shipping=shipping, purchase_tax=tax,
                           total=bid + shipping + tax)


# --------------------------------------------------------------------------
# Selling side
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class SaleProceeds:
    sale_price: Decimal
    buyer_paid_shipping: Decimal
    marketplace_fee: Decimal
    payment_processing: Decimal
    outbound_shipping: Decimal
    packaging: Decimal
    risk_allowance: Decimal
    total_expenses: Decimal
    net_proceeds: Decimal
    marketplace: str


def marketplace_fees(profile: FeeProfile, sale_price: Decimal,
                     buyer_paid_shipping: Decimal = ZERO) -> tuple[Decimal, Decimal]:
    """Return (marketplace fee, payment processing fee) using the profile's real rules."""
    base = sale_price + (buyer_paid_shipping if profile.fees_apply_to_buyer_shipping else ZERO)
    collected = sale_price + buyer_paid_shipping
    if collected <= 0:
        return ZERO, ZERO
    if (profile.flat_fee_threshold is not None and profile.flat_fee is not None
            and base < profile.flat_fee_threshold):
        fee = profile.flat_fee
    else:
        fee = base * profile.percent_rate + profile.fixed_fee
    processing = collected * profile.processing_rate + profile.processing_fixed
    return round_cents(fee), round_cents(processing)


def sale_proceeds(
    sale_price: Decimal,
    profile: FeeProfile,
    *,
    outbound_shipping: Decimal = ZERO,
    packaging: Decimal = ZERO,
    risk_reserve_rate: Decimal = ZERO,
    buyer_paid_shipping: Decimal = ZERO,
) -> SaleProceeds:
    """Expected net proceeds after every selling expense.

    ``sale_price`` is what the buyer pays for the item. If the buyer pays
    shipping separately, give it as ``buyer_paid_shipping``; otherwise
    treat ``sale_price`` as the buyer's total and ``outbound_shipping`` as
    the label cost we pay out of it.
    """
    sale_price = round_cents(sale_price)
    buyer_ship = round_cents(buyer_paid_shipping)
    outbound = round_cents(outbound_shipping)
    packaging = round_cents(packaging)
    if min(sale_price, buyer_ship, outbound, packaging, D(risk_reserve_rate)) < 0:
        raise ValueError("Sale inputs must not be negative.")
    fee, processing = marketplace_fees(profile, sale_price, buyer_ship)
    risk = round_cents(sale_price * D(risk_reserve_rate))
    expenses = fee + processing + outbound + packaging + risk
    return SaleProceeds(
        sale_price=sale_price, buyer_paid_shipping=buyer_ship, marketplace_fee=fee,
        payment_processing=processing, outbound_shipping=outbound, packaging=packaging,
        risk_allowance=risk, total_expenses=expenses,
        net_proceeds=sale_price + buyer_ship - expenses, marketplace=profile.name,
    )


# --------------------------------------------------------------------------
# Profit
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ProfitResult:
    acquisition: AcquisitionCost
    sale: SaleProceeds
    net_profit: Decimal
    roi: Decimal | None  # net profit / all-in cost (None if cost is zero)
    profit_margin: Decimal | None  # net profit / sale price
    gross_resale_multiple: Decimal | None  # sale price / all-in cost (NOT a profit measure)


def evaluate(bid: Decimal, sale: SaleProceeds, terms: PurchaseTerms) -> ProfitResult:
    acq = acquisition_cost(bid, terms)
    profit = sale.net_proceeds - acq.total
    q = Decimal("0.0001")
    roi = (profit / acq.total).quantize(q) if acq.total > 0 else None
    margin = (profit / sale.sale_price).quantize(q) if sale.sale_price > 0 else None
    multiple = (sale.sale_price / acq.total).quantize(q) if acq.total > 0 else None
    return ProfitResult(acquisition=acq, sale=sale, net_profit=profit, roi=roi,
                        profit_margin=margin, gross_resale_multiple=multiple)
