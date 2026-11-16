"""Financial engine tests. All figures are SYNTHETIC examples."""

import time
from decimal import Decimal as Dec

import pytest

from profit_hunter.config import default_fee_profiles
from profit_hunter.engine import max_bid as mb
from profit_hunter.engine.decision import DecisionInputs, Recommendation, decide
from profit_hunter.engine.max_bid import check_constraints, max_profitable_bid
from profit_hunter.engine.profit import acquisition_cost, evaluate, marketplace_fees, sale_proceeds
from profit_hunter.money import D, round_cents

from .conftest import constraints, synth_sale, terms


# ---------------------------------------------------------------- money
def test_floats_are_rejected_for_money():
    with pytest.raises(TypeError):
        D(0.1)


def test_rounding_is_half_up_to_the_cent():
    assert round_cents("1.005") == Dec("1.01")
    assert round_cents("1.004") == Dec("1.00")


# ---------------------------------------------------------------- sale side
def test_sale_proceeds_breakdown():
    s = synth_sale("40.00")
    assert s.marketplace_fee == Dec("5.84")  # 40 x 13.6% + 0.40
    assert s.risk_allowance == Dec("2.00")
    assert s.total_expenses == Dec("13.84")  # 5.84 + 5.50 + 0.50 + 2.00
    assert s.net_proceeds == Dec("26.16")
    assert s.net_proceeds < s.sale_price  # proceeds are never the sale price


def test_tiered_and_processing_fee_profiles():
    profiles = default_fee_profiles()
    assert marketplace_fees(profiles["poshmark"], Dec("14.00")) == (Dec("2.95"), Dec("0.00"))
    assert marketplace_fees(profiles["poshmark"], Dec("15.00")) == (Dec("3.00"), Dec("0.00"))
    assert marketplace_fees(profiles["depop"], Dec("20.00")) == (Dec("0.00"), Dec("1.11"))
    assert marketplace_fees(profiles["vinted"], Dec("20.00")) == (Dec("0.00"), Dec("0.00"))


def test_fee_on_buyer_paid_shipping_depends_on_profile():
    ebay, mercari = default_fee_profiles()["ebay"], default_fee_profiles()["mercari"]
    with_ship = sale_proceeds(Dec("20"), ebay, buyer_paid_shipping=Dec("5"), outbound_shipping=Dec("5"))
    assert with_ship.marketplace_fee == Dec("3.80")  # (20 + 5) x 13.6% + 0.40
    assert sale_proceeds(Dec("20"), mercari, buyer_paid_shipping=Dec("5")).marketplace_fee == Dec("2.00")


# ---------------------------------------------------------------- buy side
def test_acquisition_cost_with_tax_on_shipping():
    c = acquisition_cost(Dec("4"), terms(shipping="9"))
    assert (c.purchase_tax, c.total) == (Dec("0.91"), Dec("13.91"))


def test_acquisition_cost_tax_not_on_shipping():
    c = acquisition_cost(Dec("4"), terms(shipping="9", tax="0.10", tax_on_shipping=False))
    assert (c.purchase_tax, c.total) == (Dec("0.40"), Dec("13.40"))


def test_roi_uses_net_profit_not_revenue():
    r = evaluate(Dec("10"), synth_sale("40.00"), terms())
    assert r.acquisition.total == Dec("10.70")
    assert r.net_profit == Dec("15.46")
    assert r.roi == Dec("1.4449")  # 15.46 / 10.70
    assert r.gross_resale_multiple == Dec("3.7383")  # 40 / 10.70, a different number
    assert r.profit_margin == Dec("0.3865")


# ---------------------------------------------------------------- max bid
def test_one_dollar_item_with_free_incremental_shipping():
    """$1 opening bid, nothing extra to ship: bid ceiling is the $10 max-bid rule."""
    r = max_profitable_bid(synth_sale("40.00"), terms(shipping="0"), constraints())
    assert r.max_bid == Dec("10.00")
    assert r.binding_constraints == [mb.MAX_BID]
    assert r.profit_at_min_bid.net_profit == Dec("25.09")  # at the $1 bid


def test_one_dollar_item_with_expensive_shipping():
    """Same item, $9 shipping: the ceiling collapses to $3 because of ROI."""
    r = max_profitable_bid(synth_sale("40.00"), terms(shipping="9"), constraints())
    assert r.max_bid == Dec("3.00")
    assert r.binding_constraints == [mb.MIN_ROI]
    assert r.individual_ceilings[mb.MAX_ALL_IN] == Dec("5.00")
    # A cheaper item with the same shipping is not worth even $1.
    r2 = max_profitable_bid(synth_sale("25.00"), terms(shipping="9"), constraints())
    assert r2.max_bid is None and mb.MIN_PROFIT in r2.binding_constraints


def test_profitable_item_exceeding_remaining_budget():
    sale = synth_sale("40.00")
    r = max_profitable_bid(sale, terms(), constraints(remaining_budget="5.00"))
    assert r.max_bid == Dec("4.00") and r.binding_constraints == [mb.WEEKLY_BUDGET]
    none = max_profitable_bid(sale, terms(), constraints(remaining_budget="1.00"))
    assert none.max_bid is None  # $1 bid costs $1.07 with tax


def test_insufficient_absolute_profit_even_with_huge_roi():
    """$18 sale nets $8.25. A $1 bid is a 671% ROI but only $7.18 profit: no bid."""
    sale = synth_sale("18.00")
    assert sale.net_proceeds == Dec("8.25")
    at_one = evaluate(Dec("1"), sale, terms())
    assert at_one.roi > Dec("6") and at_one.net_profit == Dec("7.18")
    r = max_profitable_bid(sale, terms(), constraints())
    assert r.max_bid is None and r.binding_constraints == [mb.MIN_PROFIT]


def test_insufficient_roi_even_with_enough_profit():
    """$4 bid + $9 shipping: $12.25 profit passes, 88% ROI fails."""
    checks = {c.name: c.passed for c in check_constraints(Dec("4"), synth_sale("40.00"),
                                                          terms(shipping="9"), constraints())}
    assert checks[mb.MIN_PROFIT] is True
    assert checks[mb.MIN_ROI] is False


def test_seller_exposure_limits_the_bid():
    sale = synth_sale("40.00")
    r = max_profitable_bid(sale, terms(), constraints(seller_exposure_remaining="3.00"))
    assert r.max_bid == Dec("2.00") and r.binding_constraints == [mb.SELLER_EXPOSURE]
    full = max_profitable_bid(sale, terms(), constraints(seller_exposure_remaining="0.00"))
    assert full.max_bid is None


def test_negative_remaining_budget_gives_no_bid():
    r = max_profitable_bid(synth_sale("40.00"), terms(), constraints(remaining_budget="-3.00"))
    assert r.max_bid is None


@pytest.mark.parametrize("price", ["12.00", "19.99", "27.50", "40.00", "95.00"])
@pytest.mark.parametrize("shipping", ["0", "2.35", "9.21"])
@pytest.mark.parametrize("tax,on_ship", [("0", True), ("0.0725", True), ("0.10", False)])
def test_solver_matches_brute_force_with_variable_taxes(price, shipping, tax, on_ship):
    """The solver must equal an exhaustive cent-by-cent scan using the real cost functions."""
    sale, t = synth_sale(price), terms(shipping, tax, on_ship)
    c = constraints(bid_increment=Dec("0.01"), min_bid=Dec("0.01"))
    passing = [Dec(n) / 100 for n in range(1, 1501)
               if all(ch.passed for ch in check_constraints(Dec(n) / 100, sale, t, c))]
    assert max_profitable_bid(sale, t, c).max_bid == (max(passing) if passing else None)


def test_max_bid_result_satisfies_every_constraint_and_next_increment_fails():
    sale, t, c = synth_sale("33.00"), terms(shipping="4.00"), constraints()
    r = max_profitable_bid(sale, t, c)
    assert all(ch.passed for ch in r.checks_at_max)
    assert not all(ch.passed for ch in check_constraints(r.max_bid + c.bid_increment, sale, t, c))


def test_larger_bid_steps_above_a_threshold():
    """Synthetic tiers: $1 steps, then $2 steps from $6. Valid bids: 1..6, 8, 10."""
    tiers = ((Dec("6"), Dec("2")),)
    c = constraints(increment_tiers=tiers)
    assert mb.bid_ladder(c, Dec("10")) == [Dec(n) for n in (1, 2, 3, 4, 5, 6, 8, 10)]
    # Budget allows a $7.48 bid; the highest PLACEABLE bid under it is $6, not $7.
    r = max_profitable_bid(synth_sale("40.00"), terms(), constraints(increment_tiers=tiers, remaining_budget="8.00"))
    assert r.max_bid == Dec("6.00")
    assert mb.increment_at(Dec("5"), Dec("1"), tiers) == Dec("1")
    assert mb.increment_at(Dec("6"), Dec("1"), tiers) == Dec("2")


def test_financial_calculation_is_fast():
    """Engineering target: well under 100 ms, even searching cent by cent."""
    sale, t = synth_sale("40.00"), terms(shipping="3.00")
    c = constraints(bid_increment=Dec("0.01"), min_bid=Dec("0.01"))
    start = time.perf_counter()
    max_profitable_bid(sale, t, c)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < 100, f"took {elapsed_ms:.1f} ms"


# ---------------------------------------------------------------- decisions
def _inputs(**kw):
    base = dict(id_confidence=Dec("0.95"), min_id_confidence=Dec("0.90"),
                max_bid=max_profitable_bid(synth_sale("40.00"), terms(), constraints()))
    base.update(kw)
    return DecisionInputs(**base)


def test_buy_when_everything_passes_but_never_authorizes_purchase():
    d = decide(_inputs())
    assert d.recommendation is Recommendation.BUY and d.max_bid == Dec("10.00")
    assert d.authorizes_purchase is False


def test_uncertain_identification_skips_without_lower_bound():
    assert decide(_inputs(id_confidence=Dec("0.70"))).recommendation is Recommendation.SKIP
    assert decide(_inputs(id_confidence=None)).recommendation is Recommendation.SKIP


def test_uncertain_identification_with_lower_bound_valuation_is_review():
    d = decide(_inputs(id_confidence=Dec("0.70"), valuation_is_lower_bound=True))
    assert d.recommendation is Recommendation.REVIEW


def test_manual_confirmation_overrides_ai_confidence():
    d = decide(_inputs(id_confidence=Dec("0.40"), manually_confirmed=True))
    assert d.recommendation is Recommendation.BUY


def test_missing_comparable_data_skips():
    d = decide(_inputs(max_bid=None))
    assert d.recommendation is Recommendation.SKIP and "valuation" in d.reasons[0]


def test_no_valid_bid_skips():
    none = max_profitable_bid(synth_sale("18.00"), terms(), constraints())
    assert decide(_inputs(max_bid=none)).recommendation is Recommendation.SKIP


def test_current_bid_already_past_the_ceiling_skips():
    assert decide(_inputs(current_bid=Dec("10"))).recommendation is Recommendation.SKIP
    assert decide(_inputs(current_bid=Dec("9"))).recommendation is Recommendation.BUY


@pytest.mark.parametrize("flag", ["authenticity_uncertain", "suspected_counterfeit", "condition_unverifiable"])
def test_risk_policy_flags_skip(flag):
    assert decide(_inputs(**{flag: True})).recommendation is Recommendation.SKIP


def test_unknown_shipping_skips_and_estimated_shipping_warns():
    assert decide(_inputs(shipping_known=False)).recommendation is Recommendation.SKIP
    d = decide(_inputs(shipping_is_estimate=True))
    assert d.recommendation is Recommendation.BUY and any("estimate" in w for w in d.warnings)


def test_below_preferred_roi_adds_warning():
    d = decide(_inputs(preferred_roi=Dec("2.00")))  # ROI at max bid is 144%
    assert any("preferred" in w for w in d.warnings)
