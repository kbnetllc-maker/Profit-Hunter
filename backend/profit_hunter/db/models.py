"""Database tables (Milestone 1 set).

Money columns end in ``_cents`` and hold whole cents as integers.
Every row that involves money carries ``is_simulated`` so practice runs
never mix with real purchases.

Tables for identifications, inventory and resales are added in later milestones.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class Seller(Base):
    __tablename__ = "sellers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(120), unique=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    sessions: Mapped[list["SellerSession"]] = relationship(back_populates="seller")


class SellerSession(Base):
    __tablename__ = "seller_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("sellers.id"))
    show_url: Mapped[str | None] = mapped_column(String(500))
    external_session_id: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")  # ACTIVE | ENDED
    # Shipping terms; NULL means unknown.
    first_item_shipping_cents: Mapped[int | None] = mapped_column(Integer)
    additional_item_shipping_cents: Mapped[int | None] = mapped_column(Integer)
    shipping_cap_cents: Mapped[int | None] = mapped_column(Integer)
    weekly_bundling: Mapped[bool] = mapped_column(Boolean, default=False)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)

    seller: Mapped[Seller] = relationship(back_populates="sessions")
    purchases: Mapped[list["Purchase"]] = relationship(back_populates="session")


class Bundle(Base):
    """A shipment: the group of purchases a seller ships together."""

    __tablename__ = "bundles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("sellers.id"))
    opened_in_session_id: Mapped[int] = mapped_column(ForeignKey("seller_sessions.id"))
    is_weekly: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="OPEN")  # OPEN | CLOSED
    estimated_weight_oz: Mapped[int | None] = mapped_column(Integer)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)

    purchases: Mapped[list["Purchase"]] = relationship(back_populates="bundle")


class Purchase(Base):
    __tablename__ = "purchases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("sellers.id"))
    session_id: Mapped[int] = mapped_column(ForeignKey("seller_sessions.id"))
    bundle_id: Mapped[int] = mapped_column(ForeignKey("bundles.id"))
    description: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(80), default="uncategorized")
    status: Mapped[str] = mapped_column(String(16), default="COMMITTED")  # COMMITTED | SETTLED | CANCELED
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    week_start: Mapped[date] = mapped_column(Date)

    # What we expected when we committed.
    winning_bid_cents: Mapped[int] = mapped_column(Integer)
    est_shipping_cents: Mapped[int] = mapped_column(Integer)  # incremental shipping estimate
    est_tax_cents: Mapped[int] = mapped_column(Integer)
    committed_total_cents: Mapped[int] = mapped_column(Integer)
    shipping_was_estimate: Mapped[bool] = mapped_column(Boolean, default=False)
    expected_net_proceeds_cents: Mapped[int | None] = mapped_column(Integer)  # projection only

    # What actually happened (filled in at settlement).
    actual_bid_cents: Mapped[int | None] = mapped_column(Integer)
    actual_shipping_cents: Mapped[int | None] = mapped_column(Integer)
    actual_tax_cents: Mapped[int | None] = mapped_column(Integer)
    actual_total_cents: Mapped[int | None] = mapped_column(Integer)

    # Share of the bundle's shipping, for inventory cost accounting.
    allocated_shipping_cents: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(DateTime)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime)

    session: Mapped[SellerSession] = relationship(back_populates="purchases")
    bundle: Mapped[Bundle] = relationship(back_populates="purchases")
    seller: Mapped[Seller] = relationship()


class BudgetWeek(Base):
    """Snapshot of the starting budget for one week, so history stays auditable."""

    __tablename__ = "budget_weeks"
    __table_args__ = (UniqueConstraint("week_start", "is_simulated"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    week_start: Mapped[date] = mapped_column(Date)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    starting_budget_cents: Mapped[int] = mapped_column(Integer)
    timezone: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class BudgetTransaction(Base):
    """Append-only log. Rows are never edited or deleted."""

    __tablename__ = "budget_transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    budget_week_id: Mapped[int] = mapped_column(ForeignKey("budget_weeks.id"))
    purchase_id: Mapped[int | None] = mapped_column(ForeignKey("purchases.id"))
    kind: Mapped[str] = mapped_column(String(16))  # see engine.ledger.TxnKind
    amount_cents: Mapped[int] = mapped_column(Integer)
    commitment_released_cents: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(String(300), default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime)


class Item(Base):
    """Something seen at auction. Attributes here are entered or confirmed by a person."""

    __tablename__ = "items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    description: Mapped[str] = mapped_column(String(500))
    category: Mapped[str] = mapped_column(String(80), default="")
    brand: Mapped[str] = mapped_column(String(120), default="")
    model: Mapped[str] = mapped_column(String(200), default="")
    size: Mapped[str] = mapped_column(String(60), default="")
    color: Mapped[str] = mapped_column(String(60), default="")
    material: Mapped[str] = mapped_column(String(120), default="")
    era: Mapped[str] = mapped_column(String(60), default="")
    condition: Mapped[str] = mapped_column(String(120), default="")
    defects: Mapped[str] = mapped_column(Text, default="")
    identifiers: Mapped[str] = mapped_column(String(200), default="")
    seller_transcript: Mapped[str] = mapped_column(Text, default="")
    manually_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class Analysis(Base):
    """One saved analysis: the exact inputs (including the settings in force)
    and the full result, so any past recommendation can be audited. Never edited."""

    __tablename__ = "analyses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    session_id: Mapped[int] = mapped_column(ForeignKey("seller_sessions.id"))
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    recommendation: Mapped[str] = mapped_column(String(8))
    max_bid_cents: Mapped[int | None] = mapped_column(Integer)
    inputs: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    item: Mapped[Item] = relationship()


class ComparableListing(Base):
    """One comparable listing found by a person, attached to an item."""

    __tablename__ = "comparable_listings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    marketplace: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(300))
    source_url: Mapped[str] = mapped_column(String(1000))
    # ACTIVE = asking price, SOLD = completed sale, AUCTION = never used as evidence.
    listing_status: Mapped[str] = mapped_column(String(8))
    price_cents: Mapped[int] = mapped_column(Integer)  # asking or sold price, excluding shipping
    shipping_price_cents: Mapped[int | None] = mapped_column(Integer)  # NULL = unknown
    condition: Mapped[str] = mapped_column(String(120), default="")
    size: Mapped[str] = mapped_column(String(60), default="")
    variation: Mapped[str] = mapped_column(String(200), default="")
    variation_status: Mapped[str] = mapped_column(String(10), default="SAME")  # SAME | PLAUSIBLE | DIFFERENT
    match_confidence_pct: Mapped[int] = mapped_column(Integer)  # 0..100
    days_to_sell: Mapped[int | None] = mapped_column(Integer)
    date_observed: Mapped[date] = mapped_column(Date)
    included: Mapped[bool] = mapped_column(Boolean, default=True)  # False = rejected by the user
    decision_reason: Mapped[str] = mapped_column(String(500), default="")  # why included or rejected
    created_at: Mapped[datetime] = mapped_column(DateTime)

    item: Mapped[Item] = relationship()


class Valuation(Base):
    """Snapshot of a valuation used by an analysis: the comparables exactly as
    they were, the rules in force and the result. Never edited."""

    __tablename__ = "valuations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    expected_sale_price_cents: Mapped[int | None] = mapped_column(Integer)  # NULL = could not be valued
    inputs: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)
