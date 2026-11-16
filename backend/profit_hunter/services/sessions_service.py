"""Seller sessions, bundles and shipping."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..db.models import Bundle, Purchase, Seller, SellerSession
from ..engine.shipping import BundleState, ShippingEstimate, ShippingTerms, allocate, incremental_shipping
from ..money import ZERO, from_cents, opt_from_cents, opt_to_cents
from . import to_db_time, utcnow


def get_or_create_seller(db: Session, username: str) -> Seller:
    username = username.strip()
    if not username:
        raise ValueError("Seller username is required.")
    seller = db.scalar(select(Seller).where(Seller.username == username))
    if seller is None:
        seller = Seller(username=username, created_at=to_db_time(utcnow()))
        db.add(seller)
        db.commit()
    return seller


def open_session(
    db: Session, seller: Seller, *,
    show_url: str | None = None,
    external_session_id: str | None = None,
    first_item_shipping: Decimal | None = None,
    additional_item_shipping: Decimal | None = None,
    shipping_cap: Decimal | None = None,
    weekly_bundling: bool = False,
    simulated: bool = False,
    now: datetime | None = None,
) -> SellerSession:
    session = SellerSession(
        seller_id=seller.id, show_url=show_url, external_session_id=external_session_id,
        first_item_shipping_cents=opt_to_cents(first_item_shipping),
        additional_item_shipping_cents=opt_to_cents(additional_item_shipping),
        shipping_cap_cents=opt_to_cents(shipping_cap),
        weekly_bundling=weekly_bundling, is_simulated=simulated,
        started_at=to_db_time(now or utcnow()),
    )
    db.add(session)
    db.commit()
    return session


def update_shipping_terms(db: Session, session: SellerSession, **terms: Decimal | None) -> SellerSession:
    """Set first_item_shipping / additional_item_shipping / shipping_cap (None = unknown)."""
    allowed = {"first_item_shipping", "additional_item_shipping", "shipping_cap"}
    if set(terms) - allowed:
        raise KeyError(f"Unknown shipping term(s): {sorted(set(terms) - allowed)}")
    for name, value in terms.items():
        setattr(session, f"{name}_cents", opt_to_cents(value))
    db.commit()
    return session


def shipping_terms(session: SellerSession) -> ShippingTerms:
    return ShippingTerms(
        first_item_shipping=opt_from_cents(session.first_item_shipping_cents),
        additional_item_shipping=opt_from_cents(session.additional_item_shipping_cents),
        shipping_cap=opt_from_cents(session.shipping_cap_cents),
    )


# --------------------------------------------------------------------------
# Bundles
# --------------------------------------------------------------------------
def get_open_bundle(db: Session, session: SellerSession) -> Bundle | None:
    """The bundle the next purchase in this session would join, if one is open.

    With weekly bundling the bundle belongs to the seller and can span
    several shows; otherwise it belongs to this one session.
    """
    q = select(Bundle).where(Bundle.seller_id == session.seller_id, Bundle.status == "OPEN",
                             Bundle.is_simulated == session.is_simulated)
    if session.weekly_bundling:
        q = q.where(Bundle.is_weekly.is_(True))
    else:
        q = q.where(Bundle.is_weekly.is_(False), Bundle.opened_in_session_id == session.id)
    return db.scalar(q.order_by(Bundle.id.desc()))


def ensure_open_bundle(db: Session, session: SellerSession, now: datetime | None = None) -> Bundle:
    bundle = get_open_bundle(db, session)
    if bundle is None:
        bundle = Bundle(seller_id=session.seller_id, opened_in_session_id=session.id,
                        is_weekly=session.weekly_bundling, is_simulated=session.is_simulated,
                        opened_at=to_db_time(now or utcnow()))
        db.add(bundle)
        db.flush()
    return bundle


def close_bundle(db: Session, bundle: Bundle, now: datetime | None = None) -> Bundle:
    """Close a bundle. The next purchase from this seller starts a new shipment."""
    if bundle.status == "OPEN":
        bundle.status, bundle.closed_at = "CLOSED", to_db_time(now or utcnow())
        db.commit()
    return bundle


def end_session(db: Session, session: SellerSession, now: datetime | None = None) -> SellerSession:
    """End a show. Its bundle closes unless the seller offers weekly bundling."""
    when = to_db_time(now or utcnow())
    if not session.weekly_bundling:
        bundle = get_open_bundle(db, session)
        if bundle is not None:
            bundle.status, bundle.closed_at = "CLOSED", when
    session.status, session.ended_at = "ENDED", when
    db.commit()
    return session


def _live_purchases(bundle: Bundle) -> list[Purchase]:
    return [p for p in bundle.purchases if p.status != "CANCELED"]


def bundle_state(bundle: Bundle | None) -> BundleState:
    if bundle is None or bundle.status != "OPEN":
        return BundleState()
    live = _live_purchases(bundle)
    actual = sum((from_cents(p.actual_shipping_cents) for p in live if p.status == "SETTLED"), ZERO)
    pending = sum((from_cents(p.est_shipping_cents) for p in live if p.status == "COMMITTED"), ZERO)
    return BundleState(is_open=True, item_count=len(live),
                       actual_shipping_paid=actual, estimated_shipping_pending=pending)


def next_item_shipping(db: Session, settings: Settings, session: SellerSession) -> ShippingEstimate:
    """Incremental shipping the next purchase in this session would add."""
    return incremental_shipping(
        shipping_terms(session), bundle_state(get_open_bundle(db, session)),
        unknown_first_item_estimate=settings.unknown_first_item_shipping_estimate,
        unknown_additional_item_estimate=settings.unknown_additional_item_shipping_estimate,
    )


def bundle_shipping_total(bundle: Bundle) -> Decimal:
    """Total shipping for the bundle: actual where settled, estimated otherwise."""
    return sum((from_cents(p.actual_shipping_cents if p.status == "SETTLED" else p.est_shipping_cents)
                for p in _live_purchases(bundle)), ZERO)


def allocate_bundle_shipping(db: Session, bundle: Bundle) -> dict[int, Decimal]:
    """Spread the bundle's total shipping equally across its items (inventory cost basis).

    The first item usually carries the whole shipping charge on the invoice;
    allocation shares it fairly so each item's true cost is known.
    """
    live = sorted(_live_purchases(bundle), key=lambda p: p.id)
    shares = allocate(bundle_shipping_total(bundle), [Decimal(1)] * len(live))
    for p, share in zip(live, shares):
        p.allocated_shipping_cents = int(share * 100)
    db.commit()
    return {p.id: share for p, share in zip(live, shares)}


@dataclass(frozen=True)
class SessionSummary:
    session_id: int
    seller_username: str
    status: str
    is_simulated: bool
    purchase_count: int
    winning_bids_total: Decimal
    actual_shipping_paid: Decimal
    estimated_shipping_pending: Decimal
    next_item_shipping: ShippingEstimate
    bundle_open: bool
    weekly_bundling: bool


def session_summary(db: Session, settings: Settings, session: SellerSession) -> SessionSummary:
    live = [p for p in session.purchases if p.status != "CANCELED"]
    bids = sum((from_cents(p.actual_bid_cents if p.status == "SETTLED" else p.winning_bid_cents)
                for p in live), ZERO)
    actual = sum((from_cents(p.actual_shipping_cents) for p in live if p.status == "SETTLED"), ZERO)
    pending = sum((from_cents(p.est_shipping_cents) for p in live if p.status == "COMMITTED"), ZERO)
    return SessionSummary(
        session_id=session.id, seller_username=session.seller.username, status=session.status,
        is_simulated=session.is_simulated, purchase_count=len(live), winning_bids_total=bids,
        actual_shipping_paid=actual, estimated_shipping_pending=pending,
        next_item_shipping=next_item_shipping(db, settings, session),
        bundle_open=get_open_bundle(db, session) is not None,
        weekly_bundling=session.weekly_bundling,
    )
