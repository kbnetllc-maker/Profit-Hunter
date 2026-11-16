"""Comparables stored in the database -> conservative valuation."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..db.models import ComparableListing, Item
from ..engine.valuation import Comparable, Valuation, ValuationPolicy, source_key, value_item
from ..money import from_cents, opt_from_cents
from . import utcnow


def today_for(settings: Settings, now: datetime | None = None) -> date:
    return (now or utcnow()).astimezone(ZoneInfo(settings.timezone)).date()


def comparables_for(db: Session, item_id: int) -> list[ComparableListing]:
    return list(db.scalars(select(ComparableListing).where(ComparableListing.item_id == item_id)
                           .order_by(ComparableListing.id)).all())


def to_engine(row: ComparableListing) -> Comparable:
    return Comparable(
        listing_status=row.listing_status, price=from_cents(row.price_cents),
        observed_on=row.date_observed, match_confidence=Decimal(row.match_confidence_pct) / 100,
        variation_status=row.variation_status, shipping_price=opt_from_cents(row.shipping_price_cents),
        included=row.included, user_reason=row.decision_reason, days_to_sell=row.days_to_sell,
        id=row.id, label=row.title, source_key=source_key(row.source_url))


def policy_for(settings: Settings, marketplace: str | None = None) -> ValuationPolicy:
    return ValuationPolicy(
        undercut_rate=settings.undercut_rate, active_only_discount=settings.active_only_discount,
        min_match_confidence=settings.min_comparable_match_confidence,
        max_age_days=settings.max_comparable_age_days, min_credible=settings.min_credible_comparables,
        buy_match_confidence=settings.buy_comparable_match_confidence,
        preferred_age_days=settings.preferred_comparable_age_days,
        # Seller pays the label out of the buyer's total -> compare price + shipping.
        include_buyer_shipping=settings.outbound_shipping_for(marketplace) > 0)


def value(db: Session, settings: Settings, item: Item, *, marketplace: str | None = None,
          identity_confirmed: bool | None = None, now: datetime | None = None) -> Valuation:
    confirmed = item.manually_confirmed if identity_confirmed is None else identity_confirmed
    return value_item([to_engine(r) for r in comparables_for(db, item.id)],
                      policy_for(settings, marketplace), identity_confirmed=confirmed,
                      today=today_for(settings, now))
