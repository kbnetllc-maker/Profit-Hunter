"""Conservative resale valuation from comparable listings.

Pure and deterministic: no database, no network, no AI.

Rules (all rates come from settings):
  A. Lowest credible comparable price.
  B. Competitive listing price  = A reduced by the undercut rate.
  C. Conservative expected sale = B, reduced again by the asking-price
     discount whenever the comparable that sets A is an ASKING price. That
     covers "asking prices only" and also a lower asking price sitting
     below a higher completed sale. No discount when a completed sale sets A.

An auction price or starting bid is never evidence of market value.

Evidence grades (thresholds come from settings; they are application
criteria, not statistical accuracy):
  * excluded    : match below the minimum (80%), or older than the maximum age (90 days)
  * credible    : used for the price. May only LOWER it, never raise it.
  * BUY grade   : credible AND match at least 90% AND seen within 60 days.
A BUY needs at least the minimum number of BUY-grade comparables. With
fewer, the same conservative price is produced but supports REVIEW only.
The same link entered twice counts once.
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
    source_key: str = ""  # normalized link; equal keys are the same listing


def source_key(url: str) -> str:
    """A link with its query string, fragment, scheme and trailing slash removed."""
    key = url.strip().lower().split("#")[0].split("?")[0].rstrip("/")
    for prefix in ("https://", "http://", "www.", "m."):
        if key.startswith(prefix):
            key = key[len(prefix):]
    return key


@dataclass(frozen=True)
class ValuationPolicy:
    undercut_rate: Decimal
    active_only_discount: Decimal
    min_match_confidence: Decimal
    max_age_days: int
    min_credible: int
    buy_match_confidence: Decimal = Decimal("0.90")
    preferred_age_days: int = 60
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
    buy_grade: bool = False


@dataclass(frozen=True)
class Valuation:
    ok: bool
    reason: str  # why no valuation was possible (empty when ok)
    lowest_credible_price: Decimal | None  # A
    lowest_comparable_id: int | None
    lowest_is_sold: bool
    competitive_listing_price: Decimal | None  # B
    expected_sale_price: Decimal | None  # C
    asking_price_discount_applied: bool
    evidence_quality: str | None
    sold_count: int
    active_count: int
    buy_grade_count: int
    supports_buy: bool  # enough BUY-grade comparables for a BUY
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
    seen_links: set[str] = set()
    for c in comparables:
        why_not = _judge(c, policy, identity_confirmed, today)
        if not why_not and c.source_key and c.source_key in seen_links:
            why_not = "Same link as another comparable: one listing is counted once."
        if why_not:
            verdicts.append(Verdict(c, False, why_not, None))
            continue
        if c.source_key:
            seen_links.add(c.source_key)
        kind = "completed sale" if c.listing_status == SOLD else "asking price"
        note = f"Credible {kind}" + (f": {c.user_reason}" if c.user_reason else ".")
        age = (today - c.observed_on).days
        strong_match = c.match_confidence >= policy.buy_match_confidence
        recent = age <= policy.preferred_age_days
        if not strong_match:
            note += (f" Match {c.match_confidence * 100:.0f}% is below "
                     f"{policy.buy_match_confidence * 100:.0f}%: supports REVIEW only.")
        if not recent:
            note += (f" Seen {age} days ago (over {policy.preferred_age_days}): used for the price, "
                     f"not counted as BUY-grade evidence.")
        if policy.include_buyer_shipping and c.shipping_price is None:
            note += " Shipping unknown, counted as $0.00."
        verdicts.append(Verdict(c, True, note, round_cents(_basis(c, policy)), strong_match and recent))

    used = [v for v in verdicts if v.used]
    sold = [v for v in used if v.comparable.listing_status == SOLD]
    active = [v for v in used if v.comparable.listing_status == ACTIVE]
    buy_grade = sum(v.buy_grade for v in used)

    def fail(reason: str) -> Valuation:
        return Valuation(
            ok=False, reason=reason, lowest_credible_price=None, lowest_comparable_id=None,
            lowest_is_sold=False, competitive_listing_price=None, expected_sale_price=None,
            asking_price_discount_applied=False, evidence_quality=None, sold_count=len(sold),
            active_count=len(active), buy_grade_count=buy_grade, supports_buy=False,
            uses_plausible_variations=False, expected_holding_days=None, verdicts=tuple(verdicts),
            steps=(), warnings=())

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
    asking_sets_price = lowest.comparable.listing_status == ACTIVE
    c_price = round_cents(b * (1 - policy.active_only_discount)) if asking_sets_price else b
    if c_price <= 0:
        return fail("The conservative sale price works out to zero.")

    basis_words = "price plus shipping" if policy.include_buyer_shipping else "item price"
    lowest_kind = "completed sale" if lowest.comparable.listing_status == SOLD else "asking price"
    steps = [
        f"A. Lowest credible comparable ({lowest_kind}, {basis_words}): ${a:.2f}.",
        f"B. Competitive listing price, {policy.undercut_rate * 100:.0f}% below A: ${b:.2f}.",
    ]
    warnings: list[str] = []
    if asking_sets_price and not sold:
        steps.append(f"C. No completed sales, only asking prices, so a further "
                     f"{policy.active_only_discount * 100:.0f}% is taken off: ${c_price:.2f}.")
        warnings.append("Valued from asking prices only. No completed sale supports this price.")
    elif asking_sets_price:
        steps.append(f"C. An asking price below the completed sales sets A. Asking prices are not "
                     f"realized prices, so a further {policy.active_only_discount * 100:.0f}% "
                     f"is taken off: ${c_price:.2f}.")
        warnings.append("An asking price below the completed sales sets the value.")
    else:
        steps.append(f"C. A completed sale sets A, so no asking-price discount: ${c_price:.2f}.")

    supports_buy = buy_grade >= policy.min_credible
    if not supports_buy:
        warnings.append(
            f"Only {buy_grade} comparable(s) are BUY grade (match at least "
            f"{policy.buy_match_confidence * 100:.0f}% and seen within {policy.preferred_age_days} days); "
            f"{policy.min_credible} are needed. This evidence supports REVIEW only.")
    aged = sum((today - v.comparable.observed_on).days > policy.preferred_age_days for v in used)
    if aged:
        warnings.append(f"{aged} comparable(s) were seen more than {policy.preferred_age_days} days ago. "
                        f"They can lower the price but do not count as BUY-grade evidence.")
    twins: dict[tuple, int] = {}
    for v in used:
        if v.comparable.label.strip():
            key = (v.comparable.label.strip().casefold(), v.basis_price)
            twins[key] = twins.get(key, 0) + 1
    if any(n > 1 for n in twins.values()):
        warnings.append("Two or more comparables have the same title and price. They may be one item "
                        "listed in several places, and so not independent evidence.")

    quality = STRONG if len(sold) >= 2 else MODERATE if sold else WEAK
    days = [v.comparable.days_to_sell for v in sold if v.comparable.days_to_sell is not None]
    holding = max(days) if days else None
    if holding is None:
        warnings.append("Time to sell is unknown: no completed sale records how long it took.")
    plausible = any(v.comparable.variation_status == PLAUSIBLE for v in used)
    if plausible:
        warnings.append("Identity is not confirmed, so versions the item might be are included "
                        "and the lowest one sets the price.")

    return Valuation(
        ok=True, reason="", lowest_credible_price=a, lowest_comparable_id=lowest.comparable.id,
        lowest_is_sold=lowest.comparable.listing_status == SOLD, competitive_listing_price=b,
        expected_sale_price=c_price, asking_price_discount_applied=asking_sets_price,
        evidence_quality=quality, sold_count=len(sold), active_count=len(active),
        buy_grade_count=buy_grade, supports_buy=supports_buy, uses_plausible_variations=plausible,
        expected_holding_days=holding, verdicts=tuple(verdicts), steps=tuple(steps),
        warnings=tuple(warnings))
