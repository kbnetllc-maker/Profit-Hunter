"""Put the pieces together: quote a maximum bid for an item in a seller session."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from ..config import Settings
from ..db.models import SellerSession
from ..engine.decision import Decision, DecisionInputs, decide
from ..engine.max_bid import BidConstraints, MaxBidResult, increment_at, max_profitable_bid
from ..engine.profit import PurchaseTerms, SaleProceeds, sale_proceeds
from ..engine.shipping import ShippingEstimate
from . import budget_service, sessions_service


@dataclass(frozen=True)
class BidQuote:
    sale: SaleProceeds | None
    shipping: ShippingEstimate
    remaining_budget: Decimal
    seller_exposure_remaining: Decimal
    max_bid: MaxBidResult | None
    decision: Decision


def quote_bid(
    db: Session, settings: Settings, session: SellerSession, *,
    expected_sale_price: Decimal | None,
    id_confidence: Decimal | None,
    manually_confirmed: bool = False,
    valuation_is_lower_bound: bool = False,
    current_bid: Decimal | None = None,
    marketplace: str | None = None,
    authenticity_uncertain: bool = False,
    suspected_counterfeit: bool = False,
    condition_unverifiable: bool = False,
    expected_holding_days: int | None = None,
    evidence_supports_buy: bool = True,
    now: datetime | None = None,
) -> BidQuote:
    """Maximum bid and BUY/REVIEW/SKIP for one item.

    ``expected_sale_price`` is the CONSERVATIVE EXPECTED SALE PRICE (the total
    the buyer pays), or None when no reliable valuation exists. It must never
    be an auction starting bid or a hoped-for asking price.
    """
    shipping = sessions_service.next_item_shipping(db, settings, session)
    budget_left, seller_left = budget_service.remaining_for_next_purchase(db, settings, session, now=now)
    db.commit()

    sale = result = None
    if expected_sale_price is not None:
        sale = sale_proceeds(
            expected_sale_price, settings.fee_profile(marketplace),
            outbound_shipping=settings.outbound_shipping_for(marketplace),
            packaging=settings.default_packaging_cost,
            risk_reserve_rate=settings.risk_reserve_rate)
        terms = PurchaseTerms(inbound_shipping=shipping.amount, tax_rate=settings.purchase_tax_rate,
                              tax_applies_to_shipping=settings.tax_applies_to_shipping)
        result = max_profitable_bid(sale, terms, BidConstraints(
            min_net_profit=settings.min_net_profit, min_roi=settings.min_roi,
            max_bid=settings.max_bid, max_all_in_cost=settings.max_all_in_cost,
            remaining_budget=budget_left, seller_exposure_remaining=seller_left,
            bid_increment=settings.bid_increment, min_bid=settings.min_bid,
            increment_tiers=settings.increment_tiers()))

    decision = decide(DecisionInputs(
        id_confidence=id_confidence, min_id_confidence=settings.min_id_confidence,
        manually_confirmed=manually_confirmed, max_bid=result,
        valuation_is_lower_bound=valuation_is_lower_bound,
        shipping_is_estimate=shipping.is_estimate, current_bid=current_bid,
        bid_increment=increment_at(current_bid or Decimal(0), settings.bid_increment,
                                   settings.increment_tiers()),
        authenticity_uncertain=authenticity_uncertain,
        suspected_counterfeit=suspected_counterfeit, condition_unverifiable=condition_unverifiable,
        preferred_roi=settings.preferred_roi,
        expected_holding_days=expected_holding_days,
        evidence_supports_buy=evidence_supports_buy,
        max_holding_days=settings.max_expected_holding_days))
    return BidQuote(sale, shipping, budget_left, seller_left, result, decision)
