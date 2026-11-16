"""Database-backed tests: settings, seller sessions, budget ledger.

All sellers, items and prices are SYNTHETIC.
"""

from datetime import timedelta
from decimal import Decimal as Dec

import pytest
from pydantic import ValidationError

from profit_hunter.config import Settings
from profit_hunter.engine.decision import Recommendation
from profit_hunter.services import analysis_service, budget_service as budget, sessions_service as sessions
from profit_hunter.services import settings_service

from .conftest import NOW


def make_session(db, name="synthetic_seller", **kw):
    kw.setdefault("first_item_shipping", Dec("5.00"))
    kw.setdefault("additional_item_shipping", Dec("0.00"))
    return sessions.open_session(db, sessions.get_or_create_seller(db, name), now=NOW, **kw)


def buy(db, settings, session, bid, **kw):
    return budget.commit_purchase(db, settings, session, description="SYNTHETIC item",
                                  winning_bid=Dec(bid), now=NOW, **kw)


# ---------------------------------------------------------------- settings
def test_default_settings_match_the_project_parameters(db):
    s = settings_service.load_settings(db)
    assert (s.weekly_budget, s.max_bid, s.max_all_in_cost) == (Dec("50.00"), Dec("10.00"), Dec("15.00"))
    assert (s.min_net_profit, s.min_roi, s.preferred_roi) == (Dec("8.00"), Dec("1.00"), Dec("2.00"))
    assert (s.max_seller_exposure, s.min_id_confidence) == (Dec("25.00"), Dec("0.90"))
    assert s.auto_purchase_enabled is False and s.human_approval_required is True


def test_settings_are_saved_exactly_and_reloaded(db):
    settings_service.update_settings(db, weekly_budget=Dec("75.25"), timezone="America/Chicago", week_start_day=6)
    s = settings_service.load_settings(db)
    assert (s.weekly_budget, s.timezone, s.week_start_day) == (Dec("75.25"), "America/Chicago", 6)
    assert s.fee_profiles["ebay"].percent_rate == Dec("0.136")


def test_invalid_settings_are_rejected(db):
    with pytest.raises(ValidationError):
        settings_service.update_settings(db, auto_purchase_enabled=True)
    with pytest.raises(ValidationError):
        settings_service.update_settings(db, human_approval_required=False)
    with pytest.raises(ValidationError):
        settings_service.update_settings(db, weekly_budget=Dec("-1"))
    with pytest.raises(ValidationError):
        settings_service.update_settings(db, timezone="Mars/Olympus")
    with pytest.raises(KeyError):
        settings_service.update_settings(db, not_a_setting=1)


def test_owner_defaults_central_time_nine_percent_tax_vinted(db):
    s = settings_service.load_settings(db)
    assert (s.timezone, s.purchase_tax_rate, s.default_sale_marketplace) == ("America/Chicago", Dec("0.09"), "vinted")
    # Vinted (unverified assumption): no seller fees, buyer pays shipping.
    q = analysis_service.quote_bid(db, s, make_session(db), expected_sale_price=Dec("20"),
                                   id_confidence=None, manually_confirmed=True, now=NOW)
    assert q.sale.net_proceeds == Dec("18.50")  # 20 - 0.50 packaging - 1.00 risk reserve
    assert q.max_bid.max_bid == Dec("3.00")  # (3 + 5 shipping) x 1.09 = 8.72 all-in, 112% ROI
    assert q.max_bid.profit_at_max.acquisition.total == Dec("8.72")


def test_bid_increment_tiers_are_saved(db):
    settings_service.update_settings(db, bid_increment_tiers=[{"from_bid": "20", "increment": "2"}])
    assert settings_service.load_settings(db).increment_tiers() == ((Dec("20"), Dec("2")),)


# ---------------------------------------------------------------- sessions + budget
def test_multiple_purchases_from_the_same_seller(db, settings):
    s = make_session(db)
    first, second = buy(db, settings, s, "5"), buy(db, settings, s, "5")
    # First item carries the $5 shipping; the second adds none. 7% tax on both.
    assert first.committed_total_cents == 1070 and second.committed_total_cents == 535
    assert first.bundle_id == second.bundle_id
    report = budget.budget_report(db, settings, now=NOW)
    assert report.seller_exposure == {"synthetic_seller": Dec("16.05")}
    assert report.ledger.pending_commitments == Dec("16.05") and report.available == Dec("33.95")

    summary = sessions.session_summary(db, settings, s)
    assert (summary.purchase_count, summary.winning_bids_total) == (2, Dec("10.00"))
    assert summary.estimated_shipping_pending == Dec("5.00") and summary.actual_shipping_paid == Dec("0")


def test_seller_exposure_limit_blocks_purchase(db, settings):
    s = make_session(db)
    buy(db, settings, s, "5"), buy(db, settings, s, "5"), buy(db, settings, s, "8")  # 10.70 + 5.35 + 8.56
    with pytest.raises(budget.SellerExposureExceeded):
        buy(db, settings, s, "1")  # 24.61 + 1.07 > 25
    assert budget.budget_report(db, settings, now=NOW).seller_exposure["synthetic_seller"] == Dec("24.61")


def test_budget_cannot_be_overspent_and_cancel_releases_capital(db, settings):
    purchases = [buy(db, settings, make_session(db, f"synthetic_seller_{n}"), "10") for n in range(3)]
    assert budget.budget_report(db, settings, now=NOW).available == Dec("1.85")  # 50 - 3 x 16.05
    fourth = make_session(db, "synthetic_seller_4")
    with pytest.raises(budget.BudgetExceeded):
        buy(db, settings, fourth, "1")  # would cost 6.42
    assert len(fourth.purchases) == 0  # nothing was saved

    budget.cancel_purchase(db, purchases[0], now=NOW)
    assert budget.budget_report(db, settings, now=NOW).available == Dec("17.90")
    buy(db, settings, fourth, "1")  # now it fits
    with pytest.raises(ValueError):
        budget.cancel_purchase(db, purchases[0], now=NOW)  # cannot cancel twice


def test_capital_stays_committed_until_settled_and_actuals_replace_estimates(db, settings):
    s = make_session(db)
    p = buy(db, settings, s, "10", expected_net_proceeds=Dec("26.16"))
    before = budget.budget_report(db, settings, now=NOW)
    assert (before.ledger.pending_commitments, before.ledger.actual_spending) == (Dec("16.05"), Dec("0"))
    # Projected proceeds are reported but never become spendable cash.
    assert before.projected_resale_proceeds == Dec("26.16") and before.available == Dec("33.95")

    budget.settle_purchase(db, p, actual_bid=Dec("10"), actual_shipping=Dec("5.75"), actual_tax=Dec("1.18"), now=NOW)
    after = budget.budget_report(db, settings, now=NOW)
    assert (after.ledger.pending_commitments, after.ledger.actual_spending) == (Dec("0.00"), Dec("16.93"))
    assert after.available == Dec("33.07")
    assert sessions.session_summary(db, settings, s).actual_shipping_paid == Dec("5.75")


def test_simulated_purchases_stay_separate_from_real_ones(db, settings):
    buy(db, settings, make_session(db, simulated=True), "10")
    real = budget.budget_report(db, settings, now=NOW, simulated=False)
    sim = budget.budget_report(db, settings, now=NOW, simulated=True)
    assert real.available == Dec("50.00") and real.seller_exposure == {}
    assert sim.available == Dec("33.95") and sim.is_simulated
    # A real session with the same seller is unaffected by simulated exposure and bundles.
    real_session = make_session(db)
    assert sessions.next_item_shipping(db, settings, real_session).amount == Dec("5.00")
    assert budget.remaining_for_next_purchase(db, settings, real_session, now=NOW) == (Dec("50.00"), Dec("25.00"))


def test_new_week_gets_a_fresh_budget_and_old_week_keeps_its_snapshot(db, settings):
    buy(db, settings, make_session(db), "10")
    next_week = NOW + timedelta(days=7)
    richer = Settings(weekly_budget=Dec("80"))
    assert budget.budget_report(db, richer, now=next_week).available == Dec("80.00")
    assert budget.budget_report(db, richer, now=NOW).ledger.starting_budget == Dec("50.00")


# ---------------------------------------------------------------- shipping through sessions
def test_bundle_cap_and_bundle_closing_through_the_database(db, settings):
    s = make_session(db, first_item_shipping=Dec("4.00"), additional_item_shipping=Dec("2.00"),
                     shipping_cap=Dec("7.00"))
    charged = [buy(db, settings, s, "1").est_shipping_cents for _ in range(4)]
    assert charged == [400, 200, 100, 0]  # capped at $7.00 in total

    bundle = sessions.get_open_bundle(db, s)
    shares = sessions.allocate_bundle_shipping(db, bundle)
    assert sorted(shares.values()) == [Dec("1.75")] * 4  # $7.00 shared for inventory cost

    sessions.close_bundle(db, bundle, now=NOW)
    assert sessions.next_item_shipping(db, settings, s).amount == Dec("4.00")  # new shipment
    assert buy(db, settings, s, "1").bundle_id != bundle.id


def test_canceled_purchase_leaves_the_bundle(db, settings):
    s = make_session(db)
    p = buy(db, settings, s, "3")
    budget.cancel_purchase(db, p, now=NOW)
    assert sessions.next_item_shipping(db, settings, s).amount == Dec("5.00")  # first-item rate again


def test_ending_a_session_closes_its_bundle_unless_weekly_bundling(db, settings):
    normal = make_session(db, "synthetic_normal")
    buy(db, settings, normal, "1")
    sessions.end_session(db, normal, now=NOW)
    assert sessions.next_item_shipping(db, settings, make_session(db, "synthetic_normal")).amount == Dec("5.00")
    with pytest.raises(ValueError):
        buy(db, settings, normal, "1")  # ended sessions accept no purchases

    weekly = make_session(db, "synthetic_weekly", weekly_bundling=True)
    buy(db, settings, weekly, "1")
    sessions.end_session(db, weekly, now=NOW)
    later_show = make_session(db, "synthetic_weekly", weekly_bundling=True)
    assert sessions.next_item_shipping(db, settings, later_show).amount == Dec("0.00")  # same bundle


def test_unknown_additional_shipping_is_estimated_and_flagged(db, settings):
    s = make_session(db, additional_item_shipping=None)
    buy(db, settings, s, "1")
    est = sessions.next_item_shipping(db, settings, s)
    assert (est.amount, est.is_estimate) == (Dec("3.00"), True)
    assert buy(db, settings, s, "1").shipping_was_estimate is True


# ---------------------------------------------------------------- end to end quote
def test_sunk_shipping_does_not_justify_an_unprofitable_item(db, settings):
    """Shipping already paid makes the next item cheaper to add, but a weak item is still SKIP."""
    s = make_session(db)
    first = analysis_service.quote_bid(db, settings, s, expected_sale_price=Dec("40"),
                                       id_confidence=Dec("0.95"), now=NOW)
    assert first.max_bid.max_bid == Dec("7.00")  # $5 shipping counts against the first item
    buy(db, settings, s, "5")

    second = analysis_service.quote_bid(db, settings, s, expected_sale_price=Dec("40"),
                                        id_confidence=Dec("0.95"), now=NOW)
    assert second.shipping.amount == Dec("0.00") and second.max_bid.max_bid == Dec("10.00")
    assert second.decision.recommendation is Recommendation.BUY

    weak = analysis_service.quote_bid(db, settings, s, expected_sale_price=Dec("18"),
                                      id_confidence=Dec("0.95"), now=NOW)
    assert weak.decision.recommendation is Recommendation.SKIP


def test_quote_respects_remaining_budget_and_missing_valuation(db, settings):
    for n in range(3):
        buy(db, settings, make_session(db, f"synthetic_seller_{n}"), "10")  # leaves $1.85
    s = make_session(db, "synthetic_other", first_item_shipping=Dec("0"))
    q = analysis_service.quote_bid(db, settings, s, expected_sale_price=Dec("40"),
                                   id_confidence=Dec("0.95"), now=NOW)
    assert q.remaining_budget == Dec("1.85") and q.max_bid.max_bid == Dec("1.00")

    none = analysis_service.quote_bid(db, settings, s, expected_sale_price=None,
                                      id_confidence=Dec("0.95"), now=NOW)
    assert none.max_bid is None and none.decision.recommendation is Recommendation.SKIP
