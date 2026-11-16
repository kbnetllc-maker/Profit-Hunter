"""Shipping and pure ledger tests. All figures are SYNTHETIC examples."""

from datetime import date, datetime, timezone
from decimal import Decimal as Dec

import pytest

from profit_hunter.engine.ledger import LedgerEntry, TxnKind, summarize, week_start_for
from profit_hunter.engine.shipping import BundleState, ShippingTerms, allocate, incremental_shipping

EST = dict(unknown_first_item_estimate=Dec("9.00"), unknown_additional_item_estimate=Dec("3.00"))


def test_first_item_uses_known_rate():
    s = incremental_shipping(ShippingTerms(first_item_shipping=Dec("5.00")), BundleState(), **EST)
    assert (s.amount, s.is_estimate) == (Dec("5.00"), False)


def test_unknown_shipping_uses_conservative_estimate_and_is_flagged():
    first = incremental_shipping(ShippingTerms(), BundleState(), **EST)
    assert (first.amount, first.is_estimate) == (Dec("9.00"), True)
    # Later items are NOT assumed to ship free when the seller's terms are unknown.
    later = incremental_shipping(ShippingTerms(first_item_shipping=Dec("5")),
                                 BundleState(is_open=True, item_count=1, actual_shipping_paid=Dec("5")), **EST)
    assert (later.amount, later.is_estimate) == (Dec("3.00"), True)


def test_known_free_additional_shipping():
    t = ShippingTerms(first_item_shipping=Dec("5"), additional_item_shipping=Dec("0"))
    s = incremental_shipping(t, BundleState(is_open=True, item_count=2, actual_shipping_paid=Dec("5")), **EST)
    assert (s.amount, s.is_estimate) == (Dec("0.00"), False)


def test_bundle_reaching_its_shipping_cap():
    t = ShippingTerms(first_item_shipping=Dec("9"), additional_item_shipping=Dec("2"), shipping_cap=Dec("12"))
    paid, charges = Dec("0"), []
    for n in range(5):
        s = incremental_shipping(t, BundleState(is_open=n > 0, item_count=n, actual_shipping_paid=paid), **EST)
        charges.append(s.amount)
        paid += s.amount
    assert charges == [Dec("9.00"), Dec("2.00"), Dec("1.00"), Dec("0.00"), Dec("0.00")]
    assert paid == Dec("12.00")


def test_closed_bundle_charges_first_item_shipping_again():
    t = ShippingTerms(first_item_shipping=Dec("9"), additional_item_shipping=Dec("0"))
    closed = BundleState(is_open=False, item_count=3, actual_shipping_paid=Dec("9"))
    assert incremental_shipping(t, closed, **EST).amount == Dec("9.00")


def test_allocation_is_exact_to_the_cent():
    shares = allocate(Dec("10.00"), [Dec(1)] * 3)
    assert shares == [Dec("3.34"), Dec("3.33"), Dec("3.33")] and sum(shares) == Dec("10.00")
    assert allocate(Dec("9.00"), [Dec(2), Dec(1)]) == [Dec("6.00"), Dec("3.00")]
    assert allocate(Dec("0"), []) == []


# ---------------------------------------------------------------- ledger
def test_commitments_hold_capital_until_canceled_or_settled():
    entries = [LedgerEntry(TxnKind.COMMIT, Dec("12.00")), LedgerEntry(TxnKind.COMMIT, Dec("8.00"))]
    s = summarize(Dec("50"), entries)
    assert (s.pending_commitments, s.actual_spending, s.available) == (Dec("20.00"), Dec("0"), Dec("30.00"))

    entries.append(LedgerEntry(TxnKind.RELEASE, Dec("8.00")))  # cancel the second
    entries.append(LedgerEntry(TxnKind.SETTLE, Dec("12.50"), commitment_released=Dec("12.00")))
    s = summarize(Dec("50"), entries)
    assert (s.pending_commitments, s.actual_spending, s.available) == (Dec("0.00"), Dec("12.50"), Dec("37.50"))


def test_resale_proceeds_never_increase_available_budget():
    s = summarize(Dec("50"), [LedgerEntry(TxnKind.COMMIT, Dec("10")), LedgerEntry(TxnKind.PROCEEDS, Dec("100"))])
    assert s.realized_proceeds == Dec("100") and s.available == Dec("40")


def test_releasing_more_than_committed_is_an_error():
    with pytest.raises(ValueError):
        summarize(Dec("50"), [LedgerEntry(TxnKind.RELEASE, Dec("5"))])


def test_week_start_respects_timezone_and_start_day():
    # 03:00 UTC Monday is still Sunday evening in New York: previous week.
    early = datetime(2026, 11, 16, 3, 0, tzinfo=timezone.utc)
    assert week_start_for(early, 0, "America/New_York") == date(2026, 11, 9)
    assert week_start_for(early, 0, "UTC") == date(2026, 11, 16)
    assert week_start_for(early, 6, "America/New_York") == date(2026, 11, 15)  # Sunday start
    with pytest.raises(ValueError):
        week_start_for(datetime(2026, 11, 16, 3, 0), 0, "UTC")
