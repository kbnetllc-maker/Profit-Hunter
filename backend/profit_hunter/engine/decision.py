"""BUY / REVIEW / SKIP decision rules.

Deterministic. A BUY recommendation NEVER authorizes a purchase: a person
must approve every purchase, and automatic purchasing does not exist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from .max_bid import MaxBidResult


class Recommendation(str, Enum):
    BUY = "BUY"
    REVIEW = "REVIEW"
    SKIP = "SKIP"


@dataclass(frozen=True)
class DecisionInputs:
    # Identification. Manually confirmed details override the AI confidence.
    id_confidence: Decimal | None
    min_id_confidence: Decimal
    manually_confirmed: bool = False

    # Valuation evidence. ``max_bid`` is None when no valuation could be made.
    max_bid: MaxBidResult | None = None
    # True when the valuation is a defensible LOWER BOUND (priced as the
    # least valuable plausible variation), so it holds even if identity is uncertain.
    valuation_is_lower_bound: bool = False

    # Shipping. ``shipping_known`` False means not even an estimate exists.
    shipping_known: bool = True
    shipping_is_estimate: bool = False

    # Auction state.
    current_bid: Decimal | None = None
    bid_increment: Decimal = Decimal("1.00")

    # Risk policy flags (any of these rejects the opportunity).
    authenticity_uncertain: bool = False
    suspected_counterfeit: bool = False
    condition_unverifiable: bool = False

    preferred_roi: Decimal | None = None


@dataclass(frozen=True)
class Decision:
    recommendation: Recommendation
    reasons: list[str]
    warnings: list[str] = field(default_factory=list)
    max_bid: Decimal | None = None
    authorizes_purchase: bool = False  # always False: human approval required


def decide(i: DecisionInputs) -> Decision:
    def skip(reason: str) -> Decision:
        return Decision(Recommendation.SKIP, [reason])

    # --- Hard rejections (risk policy) ------------------------------------
    if i.suspected_counterfeit:
        return skip("Suspected counterfeit product.")
    if i.authenticity_uncertain:
        return skip("Authenticity is uncertain.")
    if i.condition_unverifiable:
        return skip("Product condition cannot be verified.")
    if i.max_bid is None:
        return skip("No reliable valuation: comparable data is missing or unusable.")
    if not i.shipping_known:
        return skip("Shipping cost is unknown and no conservative estimate is available.")
    if i.max_bid.max_bid is None:
        return skip(i.max_bid.reason)

    ceiling = i.max_bid.max_bid
    if i.current_bid is not None:
        next_bid = i.current_bid + i.bid_increment
        if next_bid > ceiling:
            return Decision(Recommendation.SKIP, [
                f"Current bid ${i.current_bid:.2f} means the next bid (${next_bid:.2f}) "
                f"would exceed the maximum bid of ${ceiling:.2f}."], max_bid=ceiling)

    warnings: list[str] = []
    if i.shipping_is_estimate:
        warnings.append("Shipping is a conservative estimate, not a verified charge.")

    # --- Identification ---------------------------------------------------
    identified = i.manually_confirmed or (
        i.id_confidence is not None and i.id_confidence >= i.min_id_confidence)
    if not identified:
        conf = "unknown" if i.id_confidence is None else f"{i.id_confidence * 100:.0f}%"
        msg = (f"Identification confidence {conf} is below the required "
               f"{i.min_id_confidence * 100:.0f}%.")
        if i.valuation_is_lower_bound:
            return Decision(Recommendation.REVIEW, [
                msg, "A lower-bound valuation exists, so the numbers work if the least "
                     "valuable plausible variation is assumed. Verify the item manually."],
                warnings, max_bid=ceiling)
        return skip(msg + " No defensible lower-bound valuation exists.")

    reasons = [f"All requirements satisfied up to a maximum bid of ${ceiling:.2f}.",
               "This is a recommendation only. Human approval is required to purchase."]
    roi = i.max_bid.profit_at_max.roi if i.max_bid.profit_at_max else None
    if i.preferred_roi is not None and roi is not None and roi < i.preferred_roi:
        warnings.append(f"At the maximum bid, ROI ({roi * 100:.0f}%) is below the preferred "
                        f"{i.preferred_roi * 100:.0f}%. A lower bid improves the return.")
    return Decision(Recommendation.BUY, reasons, warnings, max_bid=ceiling)
