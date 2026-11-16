"""Conservative resale valuation from comparable listings.

Pure and deterministic: no database, no network, no AI.

Rules (all rates come from settings):
  A. Lowest credible comparable price.
  B. Competitive listing price  = A reduced by the undercut rate.
  C. Conservative expected sale = B, reduced again by the active-only
     discount when NO credible completed sale exists (asking prices only).

An auction price or starting bid is never evidence of market value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..money import ZERO, round_cents

ACTIVE, SOLD, AUCTION = "ACTIVE", "SOLD", "AUCTION"
LISTING_STATUSES = (ACTIVE, SOLD, AUCTION)

# How the comparable relates to the item being valued.
SAME, PLAUSIBLE, DIFFERENT = "SAME", "PLAUSIBLE", "DIFFERENT"
VARIATION_STATUSES = (SAME, PLAUSIBLE, DIFFERENT)

STRONG, MODERATE, WEAK = "STRONG", "MODERATE", "WEAK"


@dataclass(frozen=True)
class Comparable:
    listing_status: str  # ACTIVE (asking price) | SOLD (completed sale) | AUCTION (never evidence)
    price: Decimal  # item price, excluding shipping
    observed_on: date
    match_confidence: Decimal  # 0..1, how closely it matches the item
    variation_status: str = SAME
    shipping_price: Decimal | None = None  # what the buyer pays for shipping; None = unknown
    included: bool = True  # False = rejected by the user
    user_reason: str = ""
    days_to_sell: int | None = None  # SOLD only, when known
    id: int | None = None
    label: str = ""


@dataclass(frozen=True)
class ValuationPolicy:
    undercut_rate: Decimal
    active_only_discount: Decimal
    min_match_confidence: Decimal
    max_age_days: int
    min_credible: int
    # True when the resale marketplace has the seller pay the outbound label out
    # of the buyer's total: comparables are then compared on price + shipping.
    # False when the buyer pays shipping separately: item price only.
    include_buyer_shipping: bool = False


@dataclass(frozen=True)
class Verdict:
    comparable: Comparable
    used: bool
    reason: str
    basis_price: Decimal | None  # the price compared, when used


@dataclass(frozen=True)
class Valuation:
    ok: bool
    reason: str  # why no valuation was possible (empty when ok)
    lowest_credible_price: Decimal | None  # A
    lowest_comparable_id: int | None
    lowest_is_sold: bool
    competitive_listing_price: Decimal | None  # B
    expected_sale_price: Decimal | None  # C
    active_only_discount_applied: bool
    evidence_quality: str | None
    sold_count: int
    active_count: int
    uses_plausible_variations: bool
    expected_holding_days: int | None  # slowest credible completed sale; None = unknown
    verdicts: tuple[Verdict, ...]
    steps: tuple[str, ...]
    warnings: tuple[str, ...]


def _judge(c: Comparable, p: ValuationPolicy, identity_confirmed: bool, today: date) -> str:
    """Return the exclusion reason, or '' when the comparable is credible."""
    if not c.included:
        return "Rejected by you" + (f": {c.user_reason}" if c.user_reason else ".")
    if c.listing_status == AUCTION:
        return "Auction price or starting bid: never evidence of market value."
    if c.variation_status == DIFFERENT:
        return "Different product variation from the item."
    if c.variation_status == PLAUSIBLE and identity_confirmed:
        return "Alternative variation, not needed because the item's identity is confirmed."
    if c.match_confidence < p.min_match_confidence:
        return (f"Match confidence {c.match_confidence * 100:.0f}% is below the required "
                f"{p.min_match_confidence * 100:.0f}%.")
    age = (today - c.observed_on).days
    if age > p.max_age_days:
        return f"Observed {age} days ago; the limit is {p.max_age_days} days."
    return ""


def _basis(c: Comparable, p: ValuationPolicy) -> Decimal:
    if p.include_buyer_shipping:
        return c.price + (c.shipping_price or ZERO)  # unknown shipping counts as 0 (the lower figure)
    return c.price


def value_item(comparables: list[Comparable], policy: ValuationPolicy, *,
               identity_confirmed: bool, today: date) -> Valuation:
    verdicts: list[Verdict] = []
    for c in comparables:
        why_not = _judge(c, policy, identity_confirmed, today)
        if why_not:
            verdicts.append(Verdict(c, False, why_not, None))
        else:
            kind = "completed sale" if c.listing_status == SOLD else "asking price"
            note = f"Credible {kind}" + (f": {c.user_reason}" if c.user_reason else ".")
            verdicts.append(Verdict(c, True, note, round_cents(_basis(c, policy))))

    used = [v for v in verdicts if v.used]
    sold = [v for v in used if v.comparable.listing_status == SOLD]
    active = [v for v in used if v.comparable.listing_status == ACTIVE]

    def fail(reason: str) -> Valuation:
        return Valuation(False, reason, None, None, False, None, None, False, None,
                         len(sold), len(active), False, None, tuple(verdicts), (), ())

    if not comparables:
        return fail("No comparables have been entered for this item.")
    if not used:
        return fail("None of the comparables is credible, so the item cannot be valued.")
    if len(used) < policy.min_credible:
        return fail(f"Only {len(used)} credible comparable(s); at least {policy.min_credible} "
                    f"are required for a valuation.")

    lowest = min(used, key=lambda v: (v.basis_price, v.comparable.listing_status != SOLD))
    a = lowest.basis_price
    b = round_cents(a * (1 - policy.undercut_rate))
    active_only = not sold
    c_price = round_cents(b * (1 - policy.active_only_discount)) if active_only else b
    if c_price <= 0:
        return fail("The conservative sale price works out to zero.")

    basis_words = "price plus shipping" if policy.include_buyer_shipping else "item price"
    lowest_kind = "completed sale" if lowest.comparable.listing_status == SOLD else "asking price"
    steps = [
        f"A. Lowest credible comparable ({lowest_kind}, {basis_words}): ${a:.2f}.",
        f"B. Competitive listing price, {policy.undercut_rate * 100:.0f}% below A: ${b:.2f}.",
    ]
    warnings: list[str] = []
    if active_only:
        steps.append(f"C. No completed sales, only asking prices, so a further "
                     f"{policy.active_only_discount * 100:.0f}% is taken off: ${c_price:.2f}.")
        warnings.append("Valued from asking prices only. No completed sale supports this price.")
    else:
        steps.append(f"C. Completed-sale evidence exists, so no asking-price discount: ${c_price:.2f}.")

    quality = STRONG if len(sold) >= 2 else MODERATE if sold else WEAK
    days = [v.comparable.days_to_sell for v in sold if v.comparable.days_to_sell is not None]
    holding = max(days) if days else None
    if holding is None:
        warnings.append("Time to sell is unknown: no completed sale records how long it took.")
    plausible = any(v.comparable.variation_status == PLAUSIBLE for v in used)
    if plausible:
        warnings.append("Identity is not confirmed, so versions the item might be are included "
                        "and the lowest one sets the price.")

    return Valuation(True, "", a, lowest.comparable.id, lowest.comparable.listing_status == SOLD,
                     b, c_price, active_only, quality, len(sold), len(active), plausible, holding,
                     tuple(verdicts), tuple(steps), tuple(warnings))
