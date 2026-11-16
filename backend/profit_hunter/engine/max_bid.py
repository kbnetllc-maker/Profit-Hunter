"""Maximum profitable bid.

The ceiling is the highest bid (in whole bid increments) at which EVERY
constraint holds at the same time:

* minimum expected net profit
* minimum expected ROI
* maximum individual bid
* maximum all-in acquisition cost
* remaining weekly budget
* remaining seller exposure

It is found by searching over real bids and pricing each one with the
actual tax/shipping functions, so costs that change with the bid are
handled correctly. The answer is then re-checked against every constraint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from .profit import ProfitResult, PurchaseTerms, SaleProceeds, evaluate

MIN_PROFIT = "min_net_profit"
MIN_ROI = "min_roi"
MAX_BID = "max_bid"
MAX_ALL_IN = "max_all_in_cost"
WEEKLY_BUDGET = "weekly_budget"
SELLER_EXPOSURE = "seller_exposure"


@dataclass(frozen=True)
class BidConstraints:
    min_net_profit: Decimal
    min_roi: Decimal  # 1.00 = 100%
    max_bid: Decimal
    max_all_in_cost: Decimal
    remaining_budget: Decimal
    # Room left under the per-seller limit. None = no seller limit applies.
    seller_exposure_remaining: Decimal | None = None
    bid_increment: Decimal = Decimal("1.00")
    min_bid: Decimal = Decimal("1.00")


@dataclass(frozen=True)
class ConstraintCheck:
    name: str
    passed: bool
    explanation: str


@dataclass(frozen=True)
class MaxBidResult:
    max_bid: Decimal | None  # None = no valid bid exists -> SKIP
    profit_at_max: ProfitResult | None
    checks_at_max: list[ConstraintCheck]
    # The highest bid each constraint would allow on its own (None = none).
    individual_ceilings: dict[str, Decimal | None]
    binding_constraints: list[str]  # which constraints set the ceiling
    reason: str
    profit_at_min_bid: ProfitResult | None = field(default=None)


def check_constraints(bid: Decimal, sale: SaleProceeds, terms: PurchaseTerms,
                      c: BidConstraints) -> list[ConstraintCheck]:
    """Check one specific bid against every constraint."""
    r = evaluate(bid, sale, terms)
    cost, profit = r.acquisition.total, r.net_profit
    roi_txt = f"{r.roi * 100:.0f}%" if r.roi is not None else "n/a"
    checks = [
        ConstraintCheck(MIN_PROFIT, profit >= c.min_net_profit,
                        f"Expected net profit ${profit:.2f} vs minimum ${c.min_net_profit:.2f}"),
        # ROI = net profit / all-in cost, compared without dividing.
        ConstraintCheck(MIN_ROI, cost > 0 and profit >= c.min_roi * cost,
                        f"Expected ROI {roi_txt} vs minimum {c.min_roi * 100:.0f}%"),
        ConstraintCheck(MAX_BID, r.acquisition.bid <= c.max_bid,
                        f"Bid ${r.acquisition.bid:.2f} vs maximum bid ${c.max_bid:.2f}"),
        ConstraintCheck(MAX_ALL_IN, cost <= c.max_all_in_cost,
                        f"All-in cost ${cost:.2f} vs maximum ${c.max_all_in_cost:.2f}"),
        ConstraintCheck(WEEKLY_BUDGET, cost <= c.remaining_budget,
                        f"All-in cost ${cost:.2f} vs remaining weekly budget ${c.remaining_budget:.2f}"),
    ]
    if c.seller_exposure_remaining is None:
        checks.append(ConstraintCheck(SELLER_EXPOSURE, True, "No seller exposure limit applies"))
    else:
        checks.append(ConstraintCheck(
            SELLER_EXPOSURE, cost <= c.seller_exposure_remaining,
            f"All-in cost ${cost:.2f} vs remaining seller exposure ${c.seller_exposure_remaining:.2f}"))
    return checks


def max_profitable_bid(sale: SaleProceeds, terms: PurchaseTerms, c: BidConstraints) -> MaxBidResult:
    inc = c.bid_increment
    if inc <= 0 or c.min_bid <= 0:
        raise ValueError("Bid increment and minimum bid must be greater than zero.")

    lo = int((c.min_bid / inc).to_integral_value(rounding=ROUND_CEILING))
    upper = max(c.max_bid, c.max_all_in_cost, sale.net_proceeds, c.min_bid)
    hi = int((upper / inc).to_integral_value(rounding=ROUND_FLOOR))

    def largest(passes) -> Decimal | None:
        """Largest bid in [lo, hi] increments that passes (costs rise with the bid)."""
        if hi < lo or not passes(lo * inc):
            return None
        a, b = lo, hi
        while a < b:
            mid = (a + b + 1) // 2
            if passes(mid * inc):
                a = mid
            else:
                b = mid - 1
        return a * inc

    def passes_all(bid: Decimal) -> bool:
        return all(ch.passed for ch in check_constraints(bid, sale, terms, c))

    def passes_one(name: str):
        return lambda bid: next(ch for ch in check_constraints(bid, sale, terms, c)
                                if ch.name == name).passed

    names = [MIN_PROFIT, MIN_ROI, MAX_BID, MAX_ALL_IN, WEEKLY_BUDGET, SELLER_EXPOSURE]
    ceilings = {n: largest(passes_one(n)) for n in names}
    best = largest(passes_all)
    min_bid = lo * inc
    at_min = evaluate(min_bid, sale, terms)

    if best is None:
        failed = [ch for ch in check_constraints(min_bid, sale, terms, c) if not ch.passed]
        why = "; ".join(ch.explanation for ch in failed)
        return MaxBidResult(
            max_bid=None, profit_at_max=None, checks_at_max=[], individual_ceilings=ceilings,
            binding_constraints=[ch.name for ch in failed],
            reason=f"No valid bid: even the minimum bid of ${min_bid:.2f} fails. {why}",
            profit_at_min_bid=at_min,
        )

    checks = check_constraints(best, sale, terms, c)
    if not all(ch.passed for ch in checks):  # safety net; should be unreachable
        raise AssertionError("Maximum bid failed its own verification.")
    binding = [n for n in names if ceilings[n] == best
               and not (n == SELLER_EXPOSURE and c.seller_exposure_remaining is None)]
    return MaxBidResult(
        max_bid=best, profit_at_max=evaluate(best, sale, terms), checks_at_max=checks,
        individual_ceilings=ceilings, binding_constraints=binding,
        reason=f"Maximum bid ${best:.2f}, limited by: {', '.join(binding) or 'search range'}",
        profit_at_min_bid=at_min,
    )
