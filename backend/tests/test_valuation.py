"""Valuation, ranking and lookup-framework tests.

ALL listings, prices and dates here are SYNTHETIC. None is real market data.
"""

import asyncio
from datetime import date, timedelta
from decimal import Decimal as Dec

import pytest

from profit_hunter import marketplaces
from profit_hunter.engine.decision import DecisionInputs, Recommendation, decide
from profit_hunter.engine.max_bid import max_profitable_bid
from profit_hunter.engine.ranking import WEIGHTS, RankInputs, rank
from profit_hunter.engine.valuation import (ACTIVE, AUCTION, DIFFERENT, MODERATE, PLAUSIBLE, SOLD, STRONG,
                                            WEAK, Comparable, ValuationPolicy, value_item)

from .conftest import constraints, synth_sale, terms

TODAY = date(2026, 11, 16)
POLICY = ValuationPolicy(undercut_rate=Dec("0.05"), active_only_discount=Dec("0.15"),
                         min_match_confidence=Dec("0.80"), max_age_days=90, min_credible=2)
_ids = iter(range(1, 10_000))


def comp(price, status=ACTIVE, **kw):
    kw.setdefault("observed_on", TODAY)
    kw.setdefault("match_confidence", Dec("0.95"))
    return Comparable(listing_status=status, price=Dec(price), id=next(_ids), **kw)


def value(comps, confirmed=True, policy=POLICY):
    return value_item(comps, policy, identity_confirmed=confirmed, today=TODAY)


# ------------------------------------------------ active versus sold evidence
def test_active_only_takes_undercut_and_asking_price_discount():
    v = value([comp("30"), comp("34")])
    assert v.ok and v.lowest_credible_price == Dec("30.00")
    assert v.competitive_listing_price == Dec("28.50")       # 30 less 5%
    assert v.expected_sale_price == Dec("24.23")             # 28.50 less 15% = 24.225
    assert v.asking_price_discount_applied and v.evidence_quality == WEAK
    assert (v.sold_count, v.active_count) == (0, 2)
    assert any("asking prices only" in w for w in v.warnings)


def test_lower_asking_price_is_still_discounted_when_a_higher_sale_exists():
    v = value([comp("30"), comp("34"), comp("32", SOLD)])
    assert v.lowest_credible_price == Dec("30.00") and not v.lowest_is_sold
    assert v.competitive_listing_price == Dec("28.50") and v.expected_sale_price == Dec("24.23")
    assert v.asking_price_discount_applied and v.evidence_quality == MODERATE
    assert any("below the completed sales" in w for w in v.warnings)
    assert not any("asking prices only" in w for w in v.warnings)


def test_completed_sale_setting_the_price_takes_no_asking_price_discount():
    v = value([comp("33"), comp("34"), comp("32", SOLD)])
    assert v.lowest_is_sold and v.expected_sale_price == v.competitive_listing_price == Dec("30.40")
    assert not v.asking_price_discount_applied


def test_same_listings_are_worth_less_as_asking_prices_than_as_sales():
    as_sold = value([comp("30", SOLD), comp("34", SOLD)])
    as_active = value([comp("30"), comp("34")])
    assert as_sold.expected_sale_price == Dec("28.50") and as_sold.evidence_quality == STRONG
    assert as_active.expected_sale_price < as_sold.expected_sale_price


def test_lowest_sold_price_sets_the_value_and_ties_prefer_the_sale():
    v = value([comp("40"), comp("28", SOLD), comp("31", SOLD)])
    assert v.lowest_credible_price == Dec("28.00") and v.lowest_is_sold
    assert v.expected_sale_price == Dec("26.60")
    tie = value([comp("30"), comp("30", SOLD)])
    assert tie.lowest_is_sold


def test_auction_starting_bid_is_never_evidence():
    v = value([comp("1", AUCTION), comp("30"), comp("34")])
    assert v.lowest_credible_price == Dec("30.00")
    excluded = [x for x in v.verdicts if not x.used]
    assert len(excluded) == 1 and "never evidence" in excluded[0].reason
    assert not value([comp("1", AUCTION), comp("2", AUCTION)]).ok


# ------------------------------------------------ incorrect product variation
def test_a_different_variation_cannot_raise_or_lower_the_value():
    base = value([comp("30"), comp("34")])
    v = value([comp("30"), comp("34"), comp("90", variation_status=DIFFERENT),
               comp("4", SOLD, variation_status=DIFFERENT)])
    assert v.expected_sale_price == base.expected_sale_price == Dec("24.23")
    assert v.sold_count == 0  # the wrong-variation sale is not evidence
    assert sum("Different product variation" in x.reason for x in v.verdicts) == 2


def test_uncertain_identity_is_priced_as_the_least_valuable_plausible_variation():
    comps = [comp("30"), comp("34"), comp("12", variation_status=PLAUSIBLE)]
    unsure = value(comps, confirmed=False)
    assert unsure.lowest_credible_price == Dec("12.00") and unsure.uses_plausible_variations
    assert unsure.expected_sale_price == Dec("9.69")         # 12 -> 11.40 -> 9.69
    sure = value(comps, confirmed=True)
    assert sure.lowest_credible_price == Dec("30.00") and not sure.uses_plausible_variations


# ------------------------------------------------ credibility filters
def test_low_match_stale_and_rejected_comparables_are_excluded_with_reasons():
    v = value([
        comp("30"), comp("34"),
        comp("10", match_confidence=Dec("0.79")),
        comp("11", observed_on=TODAY - timedelta(days=91)),
        comp("12", included=False, user_reason="stained"),
    ])
    assert v.lowest_credible_price == Dec("30.00")
    reasons = [x.reason for x in v.verdicts if not x.used]
    assert "Match confidence 79%" in reasons[0] and "91 days ago" in reasons[1]
    assert reasons[2] == "Rejected by you: stained"
    edge = value([comp("30", match_confidence=Dec("0.80")), comp("20", observed_on=TODAY - timedelta(days=90))])
    assert edge.ok and edge.lowest_credible_price == Dec("20.00")  # exactly at both limits counts


def test_too_little_evidence_gives_no_valuation():
    assert value([]).reason == "No comparables have been entered for this item."
    one = value([comp("30", SOLD)])
    assert not one.ok and one.expected_sale_price is None and "at least 2" in one.reason
    none = value([comp("30", included=False), comp("31", AUCTION)])
    assert not none.ok and "None of the comparables is credible" in none.reason


def test_price_basis_follows_who_pays_for_shipping():
    comps = [comp("20", shipping_price=Dec("5")), comp("24")]  # second: shipping unknown
    assert value(comps).lowest_credible_price == Dec("20.00")  # buyer pays shipping separately
    total = ValuationPolicy(**{**vars(POLICY), "include_buyer_shipping": True})
    v = value(comps, policy=total)
    assert v.lowest_credible_price == Dec("24.00")  # 25 vs 24 (+0 unknown)
    notes = [x.reason for x in v.verdicts]
    assert "Shipping unknown" not in notes[0] and "Shipping unknown, counted as $0.00" in notes[1]
    free = value([comp("20", shipping_price=Dec("0")), comp("24", shipping_price=Dec("3"))], policy=total)
    assert not any("unknown" in x.reason for x in free.verdicts)  # confirmed free is not "unknown"


def test_holding_time_is_the_slowest_credible_sale_or_unknown():
    v = value([comp("30", SOLD, days_to_sell=10), comp("31", SOLD, days_to_sell=40), comp("29")])
    assert v.expected_holding_days == 40
    unknown = value([comp("30", SOLD), comp("31", SOLD)])
    assert unknown.expected_holding_days is None and any("unknown" in w for w in unknown.warnings)


def test_valuation_is_deterministic_and_independent_of_entry_order():
    comps = [comp("30"), comp("34"), comp("32", SOLD)]
    first, again, reordered = value(comps), value(comps), value(list(reversed(comps)))
    assert first == again
    assert (reordered.expected_sale_price, reordered.lowest_comparable_id) == (
        first.expected_sale_price, first.lowest_comparable_id)


# ------------------------------------------------ holding risk in the decision
def test_excessive_holding_time_is_skipped():
    result = max_profitable_bid(synth_sale("60"), terms("5"), constraints())
    base = dict(id_confidence=None, min_id_confidence=Dec("0.9"), manually_confirmed=True, max_bid=result,
                max_holding_days=90)
    slow = decide(DecisionInputs(**base, expected_holding_days=91))
    assert slow.recommendation == Recommendation.SKIP and "holding risk" in slow.reasons[0]
    assert decide(DecisionInputs(**base, expected_holding_days=90)).recommendation == Recommendation.BUY
    assert decide(DecisionInputs(**base, expected_holding_days=None)).recommendation == Recommendation.BUY


# ------------------------------------------------ ranking
def rank_inputs(**kw):
    base = dict(net_profit=Dec("12"), roi=Dec("1.5"), all_in_cost=Dec("8"), incremental_shipping=Dec("2"),
                min_net_profit=Dec("8"), preferred_roi=Dec("2"), max_all_in_cost=Dec("15"),
                id_confidence=Dec("1"), evidence_quality=MODERATE, holding_days=30, max_holding_days=90,
                category_share=Dec("0.5"))
    return RankInputs(**{**base, **kw})


def test_rank_score_is_the_sum_of_its_documented_parts():
    r = rank(rank_inputs())
    assert r.components == {
        "net_profit": Dec("18.8"),               # 12/16 of 25 = 18.75, shown to one decimal
        "roi": Dec("15.0"),                      # 1.5/2 of 20
        "evidence_quality": Dec("9.0"),          # MODERATE = 0.6 of 15
        "capital_required": Dec("4.7"),          # (1 - 8/15) of 10
        "id_confidence": Dec("10.0"),
        "resale_speed": Dec("6.7"),              # (1 - 30/90) of 10
        "incremental_shipping": Dec("3.8"),      # (1 - 2/8) of 5
        "inventory_concentration": Dec("2.5"),   # (1 - 0.5) of 5
    }
    assert r.total == sum(r.components.values()) == Dec("70.5")
    assert sum(WEIGHTS.values()) == 100


def test_rank_is_not_roi_alone_and_stays_within_bounds():
    high_roi_weak = rank(rank_inputs(roi=Dec("3"), evidence_quality=WEAK, holding_days=None, net_profit=Dec("8")))
    lower_roi_strong = rank(rank_inputs(roi=Dec("1.5"), evidence_quality=STRONG, holding_days=7, net_profit=Dec("16")))
    assert lower_roi_strong.total > high_roi_weak.total
    best = rank(rank_inputs(net_profit=Dec("99"), roi=Dec("9"), all_in_cost=Dec("0.01"), incremental_shipping=Dec("0"),
                            evidence_quality=STRONG, holding_days=0, category_share=Dec("0")))
    worst = rank(rank_inputs(net_profit=Dec("-5"), roi=None, all_in_cost=Dec("20"), incremental_shipping=Dec("20"),
                             id_confidence=Dec("0"), evidence_quality=None, holding_days=None,
                             category_share=Dec("1")))
    assert worst.total == 0 and Dec("99") < best.total <= 100


# ------------------------------------------------ lookup framework
def test_no_automatic_marketplace_adapter_is_installed():
    assert marketplaces.ADAPTERS == {}


def test_lookup_times_out_and_reports_failure_instead_of_inventing_data():
    class Slow:
        name = "SYNTHETIC slow market"

        async def search(self, query):
            await asyncio.sleep(1)
            return []

    class Broken:
        name = "SYNTHETIC broken market"

        async def search(self, query):
            raise RuntimeError("boom")

    with pytest.raises(marketplaces.LookupFailed, match="did not answer"):
        asyncio.run(marketplaces.lookup(Slow(), "x", timeout_seconds=0.01))
    with pytest.raises(marketplaces.LookupFailed, match="boom"):
        asyncio.run(marketplaces.lookup(Broken(), "x"))
