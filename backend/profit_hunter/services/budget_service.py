"""Weekly budget ledger backed by the database.

Real and simulated purchases use completely separate ledgers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..db.models import BudgetTransaction, BudgetWeek, Purchase, SellerSession
from ..engine.ledger import LedgerEntry, TxnKind, WeekSummary, summarize, week_start_for
from ..engine.profit import PurchaseTerms, acquisition_cost
from ..money import ZERO, from_cents, opt_to_cents, round_cents, to_cents
from . import sessions_service, to_db_time, utcnow


class BudgetError(Exception):
    """A purchase was refused to protect the budget."""


class BudgetExceeded(BudgetError):
    pass


class SellerExposureExceeded(BudgetError):
    pass


def current_week_start(settings: Settings, now: datetime | None = None) -> date:
    return week_start_for(now or utcnow(), settings.week_start_day, settings.timezone)


def get_or_create_week(db: Session, settings: Settings, week_start: date, simulated: bool) -> BudgetWeek:
    week = db.scalar(select(BudgetWeek).where(BudgetWeek.week_start == week_start,
                                              BudgetWeek.is_simulated == simulated))
    if week is None:
        week = BudgetWeek(week_start=week_start, is_simulated=simulated,
                          starting_budget_cents=to_cents(settings.weekly_budget),
                          timezone=settings.timezone, created_at=to_db_time(utcnow()))
        db.add(week)
        db.flush()
    return week


def apply_budget_to_current_week(db: Session, settings: Settings, now: datetime | None = None) -> None:
    """After the weekly budget setting changes, use it for the CURRENT week too.

    Earlier weeks keep the budget they had, so history stays accurate.
    """
    week_start = current_week_start(settings, now)
    for week in db.scalars(select(BudgetWeek).where(BudgetWeek.week_start == week_start)).all():
        week.starting_budget_cents = to_cents(settings.weekly_budget)
    db.commit()


def _ledger(db: Session, week: BudgetWeek) -> WeekSummary:
    rows = db.scalars(select(BudgetTransaction).where(BudgetTransaction.budget_week_id == week.id)).all()
    entries = [LedgerEntry(TxnKind(r.kind), from_cents(r.amount_cents),
                           from_cents(r.commitment_released_cents)) for r in rows]
    return summarize(from_cents(week.starting_budget_cents), entries)


def _purchase_exposure(p: Purchase) -> Decimal:
    if p.status == "SETTLED":
        return from_cents(p.actual_total_cents)
    if p.status == "COMMITTED":
        return from_cents(p.committed_total_cents)
    return ZERO


def seller_exposure(db: Session, seller_id: int, week_start: date, simulated: bool) -> Decimal:
    """Money committed to or spent with one seller in the given budget week."""
    rows = db.scalars(select(Purchase).where(
        Purchase.seller_id == seller_id, Purchase.week_start == week_start,
        Purchase.is_simulated == simulated)).all()
    return sum((_purchase_exposure(p) for p in rows), ZERO)


@dataclass(frozen=True)
class BudgetReport:
    week_start: date
    is_simulated: bool
    ledger: WeekSummary
    seller_exposure: dict[str, Decimal]
    purchases_by_category: dict[str, Decimal]
    # Projection only. Never counted as available cash.
    projected_resale_proceeds: Decimal

    @property
    def available(self) -> Decimal:
        return self.ledger.available


def budget_report(db: Session, settings: Settings, *, now: datetime | None = None,
                  simulated: bool = False) -> BudgetReport:
    week_start = current_week_start(settings, now)
    week = get_or_create_week(db, settings, week_start, simulated)
    db.commit()
    purchases = db.scalars(select(Purchase).where(
        Purchase.week_start == week_start, Purchase.is_simulated == simulated,
        Purchase.status != "CANCELED")).all()
    by_seller: dict[str, Decimal] = {}
    by_category: dict[str, Decimal] = {}
    projected = ZERO
    for p in purchases:
        cost = _purchase_exposure(p)
        by_seller[p.seller.username] = by_seller.get(p.seller.username, ZERO) + cost
        by_category[p.category] = by_category.get(p.category, ZERO) + cost
        if p.expected_net_proceeds_cents is not None:
            projected += from_cents(p.expected_net_proceeds_cents)
    return BudgetReport(week_start, simulated, _ledger(db, week), by_seller, by_category, projected)


def remaining_for_next_purchase(db: Session, settings: Settings, session: SellerSession, *,
                                now: datetime | None = None) -> tuple[Decimal, Decimal]:
    """(remaining weekly budget, remaining seller exposure) for a purchase in this session."""
    week_start = current_week_start(settings, now)
    week = get_or_create_week(db, settings, week_start, session.is_simulated)
    exposure = seller_exposure(db, session.seller_id, week_start, session.is_simulated)
    return _ledger(db, week).available, settings.max_seller_exposure - exposure


def commit_purchase(
    db: Session, settings: Settings, session: SellerSession, *,
    description: str,
    winning_bid: Decimal,
    category: str = "uncategorized",
    expected_net_proceeds: Decimal | None = None,
    now: datetime | None = None,
) -> Purchase:
    """Record a won auction (entered by a person) and reserve its capital.

    Refused, with nothing saved, if it would exceed the weekly budget or the
    seller exposure limit. Shipping is the INCREMENTAL shipping for this item.
    """
    if session.status != "ACTIVE":
        raise ValueError("This seller session has ended. Open a new session first.")
    now = now or utcnow()
    shipping = sessions_service.next_item_shipping(db, settings, session)
    cost = acquisition_cost(round_cents(winning_bid), PurchaseTerms(
        inbound_shipping=shipping.amount, tax_rate=settings.purchase_tax_rate,
        tax_applies_to_shipping=settings.tax_applies_to_shipping))

    available, seller_room = remaining_for_next_purchase(db, settings, session, now=now)
    if cost.total > available:
        db.rollback()
        raise BudgetExceeded(
            f"All-in cost ${cost.total:.2f} exceeds the remaining weekly budget of ${available:.2f}.")
    if cost.total > seller_room:
        db.rollback()
        raise SellerExposureExceeded(
            f"All-in cost ${cost.total:.2f} exceeds the remaining exposure allowed for seller "
            f"'{session.seller.username}' (${max(seller_room, ZERO):.2f} of "
            f"${settings.max_seller_exposure:.2f} left).")

    week_start = current_week_start(settings, now)
    week = get_or_create_week(db, settings, week_start, session.is_simulated)
    bundle = sessions_service.ensure_open_bundle(db, session, now)
    purchase = Purchase(
        seller_id=session.seller_id, session_id=session.id, bundle_id=bundle.id,
        description=description, category=category, is_simulated=session.is_simulated,
        week_start=week_start, winning_bid_cents=to_cents(cost.bid),
        est_shipping_cents=to_cents(cost.inbound_shipping), est_tax_cents=to_cents(cost.purchase_tax),
        committed_total_cents=to_cents(cost.total), shipping_was_estimate=shipping.is_estimate,
        expected_net_proceeds_cents=opt_to_cents(expected_net_proceeds),
        created_at=to_db_time(now),
    )
    db.add(purchase)
    db.flush()
    db.add(BudgetTransaction(budget_week_id=week.id, purchase_id=purchase.id, kind=TxnKind.COMMIT.value,
                             amount_cents=purchase.committed_total_cents, note="Purchase committed",
                             occurred_at=to_db_time(now)))
    db.commit()
    return purchase


def _week_of(db: Session, purchase: Purchase) -> BudgetWeek:
    return db.scalar(select(BudgetWeek).where(BudgetWeek.week_start == purchase.week_start,
                                              BudgetWeek.is_simulated == purchase.is_simulated))


def cancel_purchase(db: Session, purchase: Purchase, *, now: datetime | None = None) -> Purchase:
    """Cancel an unsettled purchase and release its capital."""
    if purchase.status != "COMMITTED":
        raise ValueError(f"Only a committed purchase can be canceled (this one is {purchase.status}).")
    now = now or utcnow()
    purchase.status, purchase.canceled_at = "CANCELED", to_db_time(now)
    db.add(BudgetTransaction(budget_week_id=_week_of(db, purchase).id, purchase_id=purchase.id,
                             kind=TxnKind.RELEASE.value, amount_cents=purchase.committed_total_cents,
                             note="Purchase canceled", occurred_at=to_db_time(now)))
    db.commit()
    return purchase


def settle_purchase(db: Session, purchase: Purchase, *, actual_bid: Decimal, actual_shipping: Decimal,
                    actual_tax: Decimal, now: datetime | None = None) -> Purchase:
    """Replace the commitment with the amounts actually charged.

    Real charges are always recorded truthfully, even if they turn out higher
    than expected; the ledger then shows the week as over budget.
    """
    if purchase.status != "COMMITTED":
        raise ValueError(f"Only a committed purchase can be settled (this one is {purchase.status}).")
    now = now or utcnow()
    amounts = [round_cents(actual_bid), round_cents(actual_shipping), round_cents(actual_tax)]
    if min(amounts) < 0:
        raise ValueError("Actual amounts must not be negative.")
    purchase.actual_bid_cents, purchase.actual_shipping_cents, purchase.actual_tax_cents = map(to_cents, amounts)
    purchase.actual_total_cents = to_cents(sum(amounts, ZERO))
    purchase.status, purchase.settled_at = "SETTLED", to_db_time(now)
    db.add(BudgetTransaction(
        budget_week_id=_week_of(db, purchase).id, purchase_id=purchase.id, kind=TxnKind.SETTLE.value,
        amount_cents=purchase.actual_total_cents,
        commitment_released_cents=purchase.committed_total_cents,
        note="Purchase settled", occurred_at=to_db_time(now)))
    db.commit()
    return purchase

