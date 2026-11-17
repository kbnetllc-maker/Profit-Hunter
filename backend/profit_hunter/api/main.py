"""Profit Hunter web API.

Start it with:  uvicorn profit_hunter.api.main:app --reload

All money travels as strings ("12.50") so nothing is ever rounded by a
browser. The browser only displays numbers; every calculation happens here.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterator

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import init_db, make_engine, make_session_factory
from zoneinfo import ZoneInfo

from ..db.models import (AiUsage, Analysis, ComparableListing, Identification, Item, ItemImage, Purchase,
                         SellerSession)
from ..db.models import Valuation as ValuationRow
from ..engine.max_bid import increment_at
from ..engine.profit import ProfitResult, PurchaseTerms, evaluate
from ..engine.ranking import WEIGHTS, RankInputs, rank
from ..engine.valuation import LISTING_STATUSES, VARIATION_STATUSES, Valuation
from ..money import ZERO, from_cents, opt_from_cents, opt_to_cents, to_cents
from ..services import (WORKSPACE, ai_ledger, analysis_service, budget_service, identity_service,
                        image_service, sessions_service, settings_service, to_db_time, utcnow,
                        valuation_service, vision_service)
from ..vision import images as vision_images
from ..vision import schema as vision_schema

app = FastAPI(title="Profit Hunter", version="0.1.0")
_factory = None
_factory_lock = threading.Lock()


def get_db() -> Iterator[Session]:
    global _factory
    with _factory_lock:  # several first requests can arrive at once
        if _factory is None:
            engine = make_engine()
            init_db(engine)
            _factory = make_session_factory(engine)
    with _factory() as db:
        yield db


@app.exception_handler(budget_service.BudgetError)
async def _budget_error(_request, exc):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(vision_service.VisionUnavailable)
async def _vision_unavailable(_request, exc):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(ai_ledger.AllowanceExceeded)
async def _allowance(_request, exc):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(ai_ledger.NoPrice)
async def _no_price(_request, exc):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(identity_service.IdentityChanged)
async def _identity_changed(_request, exc):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(ValueError)
async def _value_error(_request, exc):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------
def money(v: Decimal | None) -> str | None:
    return None if v is None else f"{v:.2f}"


def iso(dt: datetime | None) -> str | None:
    return None if dt is None else dt.replace(tzinfo=timezone.utc).isoformat()


def purchase_json(p: Purchase) -> dict:
    settled = p.status == "SETTLED"
    return {
        "id": p.id, "session_id": p.session_id, "seller": p.seller.username,
        "description": p.description, "category": p.category, "status": p.status,
        "is_simulated": p.is_simulated,
        "bid": money(from_cents(p.actual_bid_cents if settled else p.winning_bid_cents)),
        "shipping": money(from_cents(p.actual_shipping_cents if settled else p.est_shipping_cents)),
        "tax": money(from_cents(p.actual_tax_cents if settled else p.est_tax_cents)),
        "total": money(from_cents(p.actual_total_cents if settled else p.committed_total_cents)),
        "amounts_are_actual": settled,
        "shipping_was_estimate": p.shipping_was_estimate and not settled,
        "expected_net_proceeds": money(opt_from_cents(p.expected_net_proceeds_cents)),
        "created_at": iso(p.created_at),
    }


def session_json(db: Session, settings: Settings, s: SellerSession, *, with_purchases: bool = True) -> dict:
    summary = sessions_service.session_summary(db, settings, s)
    _, seller_room = budget_service.remaining_for_next_purchase(db, settings, s)
    db.commit()
    out = {
        "id": s.id, "seller": s.seller.username, "show_url": s.show_url,
        "external_session_id": s.external_session_id, "status": s.status,
        "is_simulated": s.is_simulated, "weekly_bundling": s.weekly_bundling,
        "first_item_shipping": money(opt_from_cents(s.first_item_shipping_cents)),
        "additional_item_shipping": money(opt_from_cents(s.additional_item_shipping_cents)),
        "shipping_cap": money(opt_from_cents(s.shipping_cap_cents)),
        "started_at": iso(s.started_at), "ended_at": iso(s.ended_at),
        "purchase_count": summary.purchase_count,
        "winning_bids_total": money(summary.winning_bids_total),
        "actual_shipping_paid": money(summary.actual_shipping_paid),
        "estimated_shipping_pending": money(summary.estimated_shipping_pending),
        "bundle_open": summary.bundle_open,
        "next_item_shipping": {"amount": money(summary.next_item_shipping.amount),
                               "is_estimate": summary.next_item_shipping.is_estimate,
                               "basis": summary.next_item_shipping.basis},
        "seller_exposure_remaining": money(seller_room),
    }
    if with_purchases:
        out["purchases"] = [purchase_json(p) for p in sorted(s.purchases, key=lambda p: p.id)]
    return out


def profit_json(r: ProfitResult) -> dict:
    return {
        "bid": money(r.acquisition.bid), "inbound_shipping": money(r.acquisition.inbound_shipping),
        "purchase_tax": money(r.acquisition.purchase_tax), "all_in_cost": money(r.acquisition.total),
        "net_profit": money(r.net_profit),
        "roi": None if r.roi is None else str(r.roi),
        "profit_margin": None if r.profit_margin is None else str(r.profit_margin),
        "gross_resale_multiple": None if r.gross_resale_multiple is None else str(r.gross_resale_multiple),
    }


def get_session_or_404(db: Session, session_id: int) -> SellerSession:
    s = db.get(SellerSession, session_id)
    if s is None:
        raise HTTPException(404, "Seller session not found.")
    return s


def get_purchase_or_404(db: Session, purchase_id: int) -> Purchase:
    p = db.get(Purchase, purchase_id)
    if p is None:
        raise HTTPException(404, "Purchase not found.")
    return p


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------
@app.get("/api/settings")
def read_settings(db: Session = Depends(get_db)) -> dict:
    return settings_service.load_settings(db).model_dump(mode="json")


@app.put("/api/settings")
def write_settings(body: dict, db: Session = Depends(get_db)) -> dict:
    try:
        settings = Settings.model_validate(body)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors())
        raise HTTPException(400, f"Settings not saved. {problems}") from None
    old = settings_service.load_settings(db)
    old_week, new_week = budget_service.current_week_start(old), budget_service.current_week_start(settings)
    if old_week != new_week:
        # Moving the week boundary now would open a fresh budget week and
        # hide what has already been spent in the current one.
        held = db.scalar(select(func.count()).select_from(Purchase).where(
            Purchase.week_start == old_week, Purchase.status != "CANCELED"))
        if held:
            raise HTTPException(400, (
                "Settings not saved. Changing the week start day or timezone now would begin a new "
                f"budget week and stop counting {held} purchase(s) already made this week. "
                "Make this change when the current week has no purchases."))
    settings_service.save_settings(db, settings)
    budget_service.apply_budget_to_current_week(db, settings)
    return settings.model_dump(mode="json")


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------
@app.get("/api/dashboard")
def dashboard(simulated: bool = False, db: Session = Depends(get_db)) -> dict:
    settings = settings_service.load_settings(db)
    report = budget_service.budget_report(db, settings, simulated=simulated)
    purchases = db.scalars(select(Purchase).where(
        Purchase.week_start == report.week_start, Purchase.is_simulated == simulated)
        .order_by(Purchase.id.desc())).all()
    expected_profit = ZERO
    for p in purchases:
        if p.status != "CANCELED" and p.expected_net_proceeds_cents is not None:
            cost = p.actual_total_cents if p.status == "SETTLED" else p.committed_total_cents
            expected_profit += from_cents(p.expected_net_proceeds_cents) - from_cents(cost)
    sessions = db.scalars(select(SellerSession).where(
        SellerSession.is_simulated == simulated, SellerSession.status == "ACTIVE")
        .order_by(SellerSession.id.desc())).all()
    led = report.ledger
    return {
        "week_start": report.week_start.isoformat(), "timezone": settings.timezone,
        "is_simulated": simulated,
        "starting_budget": money(led.starting_budget), "available": money(led.available),
        "pending_commitments": money(led.pending_commitments),
        "actual_spending": money(led.actual_spending), "committed_total": money(led.committed_total),
        "over_budget": led.over_budget,
        "projected_resale_proceeds": money(report.projected_resale_proceeds),
        "expected_profit": money(expected_profit),
        "realized_proceeds": money(led.realized_proceeds),
        "realized_profit": None,  # tracked from Milestone 5 (inventory and resales)
        "max_seller_exposure": money(settings.max_seller_exposure),
        "seller_exposure": {k: money(v) for k, v in report.seller_exposure.items()},
        "purchases_by_category": {k: money(v) for k, v in report.purchases_by_category.items()},
        "purchases": [purchase_json(p) for p in purchases],
        "active_sessions": [session_json(db, settings, s, with_purchases=False) for s in sessions],
    }


# --------------------------------------------------------------------------
# Seller sessions and purchases
# --------------------------------------------------------------------------
class SessionCreate(BaseModel):
    seller_username: str
    show_url: str | None = None
    external_session_id: str | None = None
    first_item_shipping: Decimal | None = Field(default=None, ge=0)
    additional_item_shipping: Decimal | None = Field(default=None, ge=0)
    shipping_cap: Decimal | None = Field(default=None, ge=0)
    weekly_bundling: bool = False
    simulated: bool = False


class ShippingTermsUpdate(BaseModel):
    first_item_shipping: Decimal | None = Field(default=None, ge=0)
    additional_item_shipping: Decimal | None = Field(default=None, ge=0)
    shipping_cap: Decimal | None = Field(default=None, ge=0)


class PurchaseCreate(BaseModel):
    description: str = Field(min_length=1)
    winning_bid: Decimal = Field(ge=0)
    category: str = "uncategorized"
    expected_net_proceeds: Decimal | None = Field(default=None, ge=0)
    # Unique per "record my win" action, so a repeat creates nothing new.
    request_id: str | None = Field(default=None, min_length=8, max_length=64)


class PurchaseSettle(BaseModel):
    actual_bid: Decimal = Field(ge=0)
    actual_shipping: Decimal = Field(ge=0)
    actual_tax: Decimal = Field(ge=0)


@app.get("/api/sessions")
def list_sessions(simulated: bool = False, db: Session = Depends(get_db)) -> list[dict]:
    settings = settings_service.load_settings(db)
    rows = db.scalars(select(SellerSession).where(SellerSession.is_simulated == simulated)
                      .order_by(SellerSession.status, SellerSession.id.desc())).all()
    return [session_json(db, settings, s) for s in rows]


@app.post("/api/sessions")
def create_session(body: SessionCreate, db: Session = Depends(get_db)) -> dict:
    seller = sessions_service.get_or_create_seller(db, body.seller_username)
    s = sessions_service.open_session(
        db, seller, show_url=body.show_url or None, external_session_id=body.external_session_id or None,
        first_item_shipping=body.first_item_shipping, additional_item_shipping=body.additional_item_shipping,
        shipping_cap=body.shipping_cap, weekly_bundling=body.weekly_bundling, simulated=body.simulated)
    return session_json(db, settings_service.load_settings(db), s)


@app.get("/api/sessions/{session_id}")
def read_session(session_id: int, db: Session = Depends(get_db)) -> dict:
    return session_json(db, settings_service.load_settings(db), get_session_or_404(db, session_id))


@app.put("/api/sessions/{session_id}/shipping")
def update_shipping(session_id: int, body: ShippingTermsUpdate, db: Session = Depends(get_db)) -> dict:
    s = sessions_service.update_shipping_terms(db, get_session_or_404(db, session_id), **body.model_dump())
    return session_json(db, settings_service.load_settings(db), s)


@app.post("/api/sessions/{session_id}/end")
def end_session(session_id: int, db: Session = Depends(get_db)) -> dict:
    s = sessions_service.end_session(db, get_session_or_404(db, session_id))
    return session_json(db, settings_service.load_settings(db), s)


@app.post("/api/sessions/{session_id}/close-bundle")
def close_bundle(session_id: int, db: Session = Depends(get_db)) -> dict:
    s = get_session_or_404(db, session_id)
    bundle = sessions_service.get_open_bundle(db, s)
    if bundle is None:
        raise HTTPException(400, "This session has no open bundle to close.")
    sessions_service.allocate_bundle_shipping(db, bundle)
    sessions_service.close_bundle(db, bundle)
    return session_json(db, settings_service.load_settings(db), s)


@app.post("/api/sessions/{session_id}/purchases")
def record_purchase(session_id: int, body: PurchaseCreate, db: Session = Depends(get_db)) -> dict:
    """Record an auction a PERSON has already won. This never places a bid."""
    settings = settings_service.load_settings(db)
    p = budget_service.commit_purchase(
        db, settings, get_session_or_404(db, session_id), description=body.description,
        winning_bid=body.winning_bid, category=body.category or "uncategorized",
        expected_net_proceeds=body.expected_net_proceeds, request_id=body.request_id)
    return purchase_json(p)


@app.post("/api/purchases/{purchase_id}/cancel")
def cancel_purchase(purchase_id: int, db: Session = Depends(get_db)) -> dict:
    return purchase_json(budget_service.cancel_purchase(db, get_purchase_or_404(db, purchase_id)))


@app.post("/api/purchases/{purchase_id}/settle")
def settle_purchase(purchase_id: int, body: PurchaseSettle, db: Session = Depends(get_db)) -> dict:
    p = budget_service.settle_purchase(db, get_purchase_or_404(db, purchase_id), **body.model_dump())
    return purchase_json(p)


# --------------------------------------------------------------------------
# Analyze item
# --------------------------------------------------------------------------
class ItemDetails(BaseModel):
    description: str = Field(min_length=1)
    category: str = ""
    brand: str = ""
    model: str = ""
    size: str = ""
    color: str = ""
    material: str = ""
    era: str = ""
    condition: str = ""
    defects: str = ""
    identifiers: str = ""
    seller_transcript: str = ""
    manually_confirmed: bool = False


ITEM_FIELDS = tuple(ItemDetails.model_fields)


def get_item_or_404(db: Session, item_id: int) -> Item:
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(404, "Item not found.")
    return item


def get_comparable_or_404(db: Session, comparable_id: int) -> ComparableListing:
    c = db.get(ComparableListing, comparable_id)
    if c is None:
        raise HTTPException(404, "Comparable not found.")
    return c


# --------------------------------------------------------------------------
# Comparable research
# --------------------------------------------------------------------------
class ComparableBody(BaseModel):
    marketplace: str = Field(min_length=1)
    title: str = Field(min_length=1)
    # Required: every comparable must be traceable to where it was seen.
    source_url: str = Field(min_length=1)
    listing_status: str
    price: Decimal = Field(gt=0)
    shipping_price: Decimal | None = Field(default=None, ge=0)
    condition: str = ""
    size: str = ""
    variation: str = ""
    variation_status: str = "SAME"
    match_confidence_pct: int = Field(ge=0, le=100)
    days_to_sell: int | None = Field(default=None, ge=0)
    date_observed: date
    included: bool = True
    decision_reason: str = ""

    @field_validator("source_url")
    @classmethod
    def _web_link(cls, v: str) -> str:
        v = v.strip()
        if not v.lower().startswith(("http://", "https://")):
            raise ValueError("must be a full web link starting with http:// or https://")
        return v

    @field_validator("listing_status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in LISTING_STATUSES:
            raise ValueError(f"must be one of {', '.join(LISTING_STATUSES)}")
        return v

    @field_validator("variation_status")
    @classmethod
    def _variation(cls, v: str) -> str:
        if v not in VARIATION_STATUSES:
            raise ValueError(f"must be one of {', '.join(VARIATION_STATUSES)}")
        return v


def comparable_json(c: ComparableListing) -> dict:
    return {
        "id": c.id, "item_id": c.item_id, "marketplace": c.marketplace, "title": c.title,
        "source_url": c.source_url, "listing_status": c.listing_status,
        "price": money(from_cents(c.price_cents)),
        "shipping_price": money(opt_from_cents(c.shipping_price_cents)),
        "condition": c.condition, "size": c.size, "variation": c.variation,
        "variation_status": c.variation_status, "match_confidence_pct": c.match_confidence_pct,
        "days_to_sell": c.days_to_sell, "date_observed": c.date_observed.isoformat(),
        "included": c.included, "decision_reason": c.decision_reason,
    }


def valuation_json(v: Valuation, comps: list[ComparableListing]) -> dict:
    rows = {c.id: c for c in comps}

    def entry(verdict) -> dict:
        return {**comparable_json(rows[verdict.comparable.id]), "used": verdict.used,
                "buy_grade": verdict.buy_grade,
                "verdict": verdict.reason, "price_compared": money(verdict.basis_price)}

    return {
        "ok": v.ok, "reason": v.reason,
        "lowest_credible_price": money(v.lowest_credible_price),
        "lowest_comparable_id": v.lowest_comparable_id,
        "competitive_listing_price": money(v.competitive_listing_price),
        "expected_sale_price": money(v.expected_sale_price),
        "asking_price_discount_applied": v.asking_price_discount_applied,
        "evidence_quality": v.evidence_quality,
        "sold_count": v.sold_count, "active_count": v.active_count,
        "buy_grade_count": v.buy_grade_count, "supports_buy": v.supports_buy,
        "expected_holding_days": v.expected_holding_days,
        "steps": list(v.steps), "warnings": list(v.warnings),
        "comparables_used": [entry(x) for x in v.verdicts if x.used],
        "comparables_excluded": [entry(x) for x in v.verdicts if not x.used],
    }


def item_json(item: Item, db: Session | None = None) -> dict:
    out = {"id": item.id, "created_at": iso(item.created_at),
           **{name: getattr(item, name) for name in ITEM_FIELDS}}
    if db is not None:
        out["identity"] = identity_service.state(db, item)
    return out


def _apply_details(db: Session, item: Item, body: "ItemDetails", *, source: str) -> None:
    """Save item details and keep the identity confirmation honest.

    A tick in "I have personally confirmed" is a person's confirmation of the
    details being saved. When identity details change through a plain edit,
    any earlier confirmation is withdrawn instead of being carried over.
    """
    before = identity_service.fingerprint(db, item) if item.id else None
    for name, value in body.model_dump(exclude={"manually_confirmed"}).items():
        setattr(item, name, value)
    db.flush()
    changed = before is not None and before != identity_service.fingerprint(db, item)
    if body.manually_confirmed and not (changed and source == "edit"):
        identity_service.confirm(db, item, source=source)
    else:
        identity_service.revoke(db, item, "Identity details were changed." if changed
                                else "Confirmation was withdrawn.")


def _check_comparable(body: ComparableBody, settings: Settings) -> None:
    if body.date_observed > valuation_service.today_for(settings):
        raise HTTPException(400, "The date observed cannot be in the future.")
    if not body.included and not body.decision_reason.strip():
        raise HTTPException(400, "Give a reason for rejecting this comparable.")


def _comparable_columns(body: ComparableBody) -> dict:
    data = body.model_dump(exclude={"price", "shipping_price"})
    return {**data, "marketplace": body.marketplace.strip().lower(), "title": body.title.strip(),
            "price_cents": to_cents(body.price), "shipping_price_cents": opt_to_cents(body.shipping_price),
            # How long a sale took only means something for a completed sale.
            "days_to_sell": body.days_to_sell if body.listing_status == "SOLD" else None}


@app.get("/api/items")
def list_items(limit: int = 50, db: Session = Depends(get_db)) -> list[dict]:
    counts = dict(db.execute(select(ComparableListing.item_id, func.count())
                             .group_by(ComparableListing.item_id)).all())
    rows = db.scalars(select(Item).order_by(Item.id.desc()).limit(min(limit, 200))).all()
    return [{**item_json(i), "comparable_count": counts.get(i.id, 0)} for i in rows]


@app.post("/api/items")
def create_item(body: ItemDetails, db: Session = Depends(get_db)) -> dict:
    item = Item(**body.model_dump(exclude={"manually_confirmed"}), created_at=to_db_time(utcnow()))
    db.add(item)
    db.flush()
    _apply_details(db, item, body, source="manual")
    db.commit()
    return item_json(item, db)


@app.put("/api/items/{item_id}")
def update_item(item_id: int, body: ItemDetails, db: Session = Depends(get_db)) -> dict:
    item = get_item_or_404(db, item_id)
    _apply_details(db, item, body, source="edit")
    db.commit()
    return item_json(item, db)


@app.get("/api/items/{item_id}")
def read_item(item_id: int, marketplace: str | None = None, db: Session = Depends(get_db)) -> dict:
    """The item, its comparables and the valuation they currently support."""
    settings = settings_service.load_settings(db)
    item = get_item_or_404(db, item_id)
    market = (marketplace or settings.default_sale_marketplace).lower()
    if market not in settings.fee_profiles:
        raise HTTPException(400, f"No fee profile is configured for marketplace '{market}'.")
    comps = valuation_service.comparables_for(db, item.id)
    v = valuation_service.value(db, settings, item, marketplace=market)
    policy = valuation_service.policy_for(settings, market)
    return {**item_json(item, db), "marketplace": market,
            # "Today" in the configured timezone, so the form and the server agree on dates.
            "today": valuation_service.today_for(settings).isoformat(),
            "price_basis": "price plus shipping" if policy.include_buyer_shipping else "item price only",
            "comparables": [comparable_json(c) for c in comps],
            "valuation": valuation_json(v, comps)}


@app.post("/api/items/{item_id}/comparables")
def add_comparable(item_id: int, body: ComparableBody, db: Session = Depends(get_db)) -> dict:
    _check_comparable(body, settings_service.load_settings(db))
    c = ComparableListing(item_id=get_item_or_404(db, item_id).id, **_comparable_columns(body),
                          created_at=to_db_time(utcnow()))
    db.add(c)
    db.commit()
    return comparable_json(c)


@app.put("/api/comparables/{comparable_id}")
def update_comparable(comparable_id: int, body: ComparableBody, db: Session = Depends(get_db)) -> dict:
    _check_comparable(body, settings_service.load_settings(db))
    c = get_comparable_or_404(db, comparable_id)
    for name, value in _comparable_columns(body).items():
        setattr(c, name, value)
    db.commit()
    return comparable_json(c)


@app.delete("/api/comparables/{comparable_id}")
def delete_comparable(comparable_id: int, db: Session = Depends(get_db)) -> dict:
    """Remove a comparable entered by mistake. Past analyses keep their own copy."""
    db.delete(get_comparable_or_404(db, comparable_id))
    db.commit()
    return {"deleted": comparable_id}


class AnalyzeRequest(BaseModel):
    session_id: int
    item: ItemDetails
    # An item already saved in Comparable Research. Empty = save a new item.
    item_id: int | None = None
    # True = derive the sale price from the item's comparables (needs item_id).
    use_comparables: bool = False
    # Conservative expected sale price entered by the user. Ignored when
    # use_comparables is true. Leave empty when there is no reliable
    # evidence; the result is then SKIP.
    expected_sale_price: Decimal | None = Field(default=None, gt=0)
    valuation_note: str = ""
    valuation_is_lower_bound: bool = False
    marketplace: str | None = None
    current_bid: Decimal | None = Field(default=None, ge=0)
    authenticity_uncertain: bool = False
    suspected_counterfeit: bool = False
    condition_unverifiable: bool = False


@app.post("/api/analyze")
def analyze(body: AnalyzeRequest, db: Session = Depends(get_db)) -> dict:
    settings = settings_service.load_settings(db)
    session = get_session_or_404(db, body.session_id)
    marketplace = (body.marketplace or settings.default_sale_marketplace).lower()
    if marketplace not in settings.fee_profiles:
        raise HTTPException(400, f"No fee profile is configured for marketplace '{marketplace}'.")
    if body.use_comparables and body.item_id is None:
        raise HTTPException(400, "Choose a researched item to value it from comparables.")

    if body.item_id is None:
        item = Item(**body.item.model_dump(exclude={"manually_confirmed"}), created_at=to_db_time(utcnow()))
        db.add(item)
        db.flush()
    else:
        item = get_item_or_404(db, body.item_id)
    # The checkbox on the Analyze form is the person's confirmation of exactly these details.
    _apply_details(db, item, body.item, source="analysis")
    confirmed = identity_service.is_confirmed(db, item)

    valuation: Valuation | None = None
    comps: list[ComparableListing] = []
    price = body.expected_sale_price
    if body.use_comparables:
        comps = valuation_service.comparables_for(db, item.id)
        valuation = valuation_service.value(db, settings, item, marketplace=marketplace,
                                            identity_confirmed=confirmed)
        price = valuation.expected_sale_price

    q = analysis_service.quote_bid(
        db, settings, session, expected_sale_price=price,
        id_confidence=None,  # AI identification arrives in Milestone 4
        manually_confirmed=confirmed,
        valuation_is_lower_bound=body.valuation_is_lower_bound, current_bid=body.current_bid,
        marketplace=marketplace, authenticity_uncertain=body.authenticity_uncertain,
        suspected_counterfeit=body.suspected_counterfeit,
        condition_unverifiable=body.condition_unverifiable,
        expected_holding_days=valuation.expected_holding_days if valuation else None,
        evidence_supports_buy=valuation.supports_buy if valuation and valuation.ok else True)

    terms = PurchaseTerms(inbound_shipping=q.shipping.amount, tax_rate=settings.purchase_tax_rate,
                          tax_applies_to_shipping=settings.tax_applies_to_shipping)
    sale_json = max_json = at_max = at_next = ranking = None
    next_bid = None
    if body.current_bid is not None:
        next_bid = body.current_bid + increment_at(body.current_bid, settings.bid_increment,
                                                   settings.increment_tiers())
    if q.sale:
        s = q.sale
        sale_json = {
            "marketplace": s.marketplace, "expected_sale_price": money(s.sale_price),
            "marketplace_fee": money(s.marketplace_fee), "payment_processing": money(s.payment_processing),
            "outbound_shipping": money(s.outbound_shipping), "packaging": money(s.packaging),
            "risk_allowance": money(s.risk_allowance), "total_expenses": money(s.total_expenses),
            "net_proceeds": money(s.net_proceeds),
            "fee_profile_verified": settings.fee_profile(marketplace).verified,
        }
        if next_bid is not None:
            at_next = profit_json(evaluate(next_bid, s, terms))
    recommendation = q.decision.recommendation.value
    if q.max_bid:
        m = q.max_bid
        max_json = {
            "max_bid": money(m.max_bid), "reason": m.reason, "binding_constraints": m.binding_constraints,
            "individual_ceilings": {k: money(v) for k, v in m.individual_ceilings.items()},
            "checks": [{"name": c.name, "passed": c.passed, "explanation": c.explanation}
                       for c in m.checks_at_max],
        }
        if m.profit_at_max:
            at_max = profit_json(m.profit_at_max)
            if recommendation != "SKIP":
                ranking = ranking_json(db, settings, session, body, m.profit_at_max, valuation, confirmed)

    reasons, warnings = list(q.decision.reasons), list(q.decision.warnings)
    if valuation is not None:
        if not valuation.ok:
            reasons.append(valuation.reason)
        elif recommendation != "SKIP":
            warnings.extend(valuation.warnings)

    if valuation is not None:
        valuation_block = {"source": "Comparables", "note": body.valuation_note,
                           "is_lower_bound": body.valuation_is_lower_bound,
                           **valuation_json(valuation, comps)}
        snapshot = ValuationRow(
            item_id=item.id, expected_sale_price_cents=opt_to_cents(valuation.expected_sale_price),
            inputs={"comparables": [comparable_json(c) for c in comps], "marketplace": marketplace,
                    "identity_confirmed": confirmed,
                    "policy": {k: str(v) for k, v in
                               vars(valuation_service.policy_for(settings, marketplace)).items()},
                    "valued_on": valuation_service.today_for(settings).isoformat()},
            result=valuation_block, created_at=to_db_time(utcnow()))
        db.add(snapshot)
        db.flush()
        valuation_block["valuation_id"] = snapshot.id
    else:
        valuation_block = {
            "source": "Entered manually by the user" if body.expected_sale_price else "None",
            "note": body.valuation_note, "is_lower_bound": body.valuation_is_lower_bound,
            "comparables_used": [], "comparables_excluded": [],
        }

    result = {
        "item": {**body.item.model_dump(), "manually_confirmed": confirmed},
        "session": {"id": session.id, "seller": session.seller.username},
        "is_simulated": session.is_simulated,
        "recommendation": recommendation,
        "reasons": reasons, "warnings": warnings,
        "authorizes_purchase": False,
        "identification": {
            # No validated confidence score exists. A model's own confidence is
            # never used; only a person's confirmation counts.
            "confidence": None, "manually_confirmed": confirmed,
            "required_confidence": str(settings.min_id_confidence),
            "evidence": ("Details confirmed by the user." if confirmed
                         else "Not confirmed by a person. AI suggestions do not count as confirmation."),
        },
        "identity_fingerprint": identity_service.fingerprint(db, item),
        "evidence_fingerprint": evidence_fingerprint(comps) if body.use_comparables else None,
        "valuation": valuation_block,
        "sale": sale_json,
        "shipping": {"amount": money(q.shipping.amount), "is_estimate": q.shipping.is_estimate,
                     "basis": q.shipping.basis},
        "purchase_tax_rate": str(settings.purchase_tax_rate),
        "remaining_budget": money(q.remaining_budget),
        "seller_exposure_remaining": money(q.seller_exposure_remaining),
        "current_bid": money(body.current_bid), "next_bid": money(next_bid),
        "max_bid": max_json, "at_max_bid": at_max, "at_next_bid": at_next,
        "preferred_roi": str(settings.preferred_roi),
        "ranking": ranking,
    }
    record = Analysis(
        item_id=item.id, session_id=session.id, is_simulated=session.is_simulated,
        recommendation=result["recommendation"],
        max_bid_cents=None if q.decision.max_bid is None else int(q.decision.max_bid * 100),
        inputs={"request": body.model_dump(mode="json"), "settings": settings.model_dump(mode="json")},
        result=result, created_at=to_db_time(utcnow()))
    db.add(record)
    db.commit()
    return analysis_json(db, record)


def ranking_json(db: Session, settings: Settings, session: SellerSession, body: AnalyzeRequest,
                 at_max: ProfitResult, valuation: Valuation | None, confirmed: bool) -> dict:
    """Score the opportunity at the MAXIMUM bid (its least favourable price)."""
    by_category = budget_service.budget_report(
        db, settings, simulated=session.is_simulated).purchases_by_category
    spent = sum(by_category.values(), ZERO)
    category = body.item.category.strip() or "uncategorized"
    score = rank(RankInputs(
        net_profit=at_max.net_profit, roi=at_max.roi, all_in_cost=at_max.acquisition.total,
        incremental_shipping=at_max.acquisition.inbound_shipping,
        min_net_profit=settings.min_net_profit, preferred_roi=settings.preferred_roi,
        max_all_in_cost=settings.max_all_in_cost,
        id_confidence=Decimal(1) if confirmed else Decimal(0),
        evidence_quality=valuation.evidence_quality if valuation else None,
        holding_days=valuation.expected_holding_days if valuation else None,
        max_holding_days=settings.max_expected_holding_days,
        category_share=by_category.get(category, ZERO) / spent if spent > 0 else ZERO))
    return {"score": str(score.total),
            "components": {k: {"points": str(v), "out_of": str(WEIGHTS[k])}
                           for k, v in score.components.items()}}


@app.get("/api/opportunities")
def opportunities(simulated: bool = False, db: Session = Depends(get_db)) -> list[dict]:
    """This week's BUY/REVIEW analyses in active sessions, best score first.

    Only the latest analysis of each item counts. A ranking is a comparison
    aid; it never authorizes a purchase.
    """
    settings = settings_service.load_settings(db)
    week_start = budget_service.current_week_start(settings)
    since = to_db_time(datetime.combine(week_start, time.min, tzinfo=ZoneInfo(settings.timezone)))
    rows = db.scalars(select(Analysis).join(SellerSession, Analysis.session_id == SellerSession.id).where(
        Analysis.is_simulated == simulated, Analysis.created_at >= since,
        SellerSession.status == "ACTIVE").order_by(Analysis.id.desc())).all()
    latest: dict[int, Analysis] = {}
    for a in rows:
        latest.setdefault(a.item_id, a)
    ranked = [a for a in latest.values() if a.recommendation != "SKIP" and a.result.get("ranking")]
    ranked.sort(key=lambda a: Decimal(a.result["ranking"]["score"]), reverse=True)
    # An analysis made before the item's identity changed is no longer an opportunity.
    # Other stale results stay listed, flagged, after the ones still current.
    cache: dict = {}
    out = [j for j in (analysis_json(db, a, cache) for a in ranked) if not j["identity_changed"]]
    db.commit()
    return sorted(out, key=lambda j: j["stale"])


def evidence_fingerprint(comps: list[ComparableListing]) -> str:
    return hashlib.sha256(json.dumps([comparable_json(c) for c in comps], sort_keys=True).encode()).hexdigest()


_NOT_FINANCIAL = ("vision_", "ai_")


def analysis_json(db: Session, a: Analysis, cache: dict | None = None) -> dict:
    """A saved analysis exactly as it was, plus whether it can still be relied on.

    The stored snapshot is never altered. ``stale_reasons`` lists what has
    changed since: identity, comparables, financial settings, or the budget.
    A stale result must be recalculated before it is used.
    """
    cache = {} if cache is None else cache
    if "settings" not in cache:
        cache["settings"] = settings_service.load_settings(db)
        cache["settings_json"] = cache["settings"].model_dump(mode="json")
    settings = cache["settings"]
    r, reasons = a.result, []

    then = r.get("identity_fingerprint")
    identity_changed = then is not None and then != identity_service.fingerprint(db, a.item)
    if identity_changed:
        reasons.append("The item's details or photos have changed.")
    if r.get("evidence_fingerprint") and r["evidence_fingerprint"] != evidence_fingerprint(
            valuation_service.comparables_for(db, a.item_id)):
        reasons.append("The comparables have changed.")
    saved = (a.inputs or {}).get("settings", {})
    if any(cache["settings_json"].get(k) != v for k, v in saved.items() if not k.startswith(_NOT_FINANCIAL)):
        reasons.append("Financial settings have changed.")
    if a.recommendation != "SKIP":
        session = db.get(SellerSession, a.session_id)
        if session.status != "ACTIVE":
            reasons.append("The seller session has ended.")
        else:
            budget_left, seller_left = budget_service.remaining_for_next_purchase(db, settings, session)
            shipping = sessions_service.next_item_shipping(db, settings, session)
            if (money(budget_left), money(seller_left), money(shipping.amount)) != (
                    r.get("remaining_budget"), r.get("seller_exposure_remaining"), r["shipping"]["amount"]):
                reasons.append("The budget, seller room or shipping for the next item has changed.")
    return {"id": a.id, "item_id": a.item_id, "created_at": iso(a.created_at), **r,
            "identity_changed": identity_changed, "stale": bool(reasons), "stale_reasons": reasons}


@app.get("/api/analyses")
def list_analyses(simulated: bool = False, limit: int = 25, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Analysis).where(Analysis.is_simulated == simulated)
                      .order_by(Analysis.id.desc()).limit(min(limit, 200))).all()
    cache: dict = {}
    out = [analysis_json(db, a, cache) for a in rows]
    db.commit()
    return out


@app.get("/api/analyses/{analysis_id}")
def read_analysis(analysis_id: int, db: Session = Depends(get_db)) -> dict:
    a = db.get(Analysis, analysis_id)
    if a is None:
        raise HTTPException(404, "Analysis not found.")
    return {**analysis_json(db, a), "inputs": a.inputs}


# --------------------------------------------------------------------------
# AI identification (evidence and suggestions only; never a decision)
# --------------------------------------------------------------------------
def get_image_or_404(db: Session, image_id: int) -> ItemImage:
    row = db.get(ItemImage, image_id)
    if row is None or row.workspace_id != WORKSPACE:
        raise HTTPException(404, "Photo not found.")
    return row


def get_identification_or_404(db: Session, identification_id: int) -> Identification:
    row = db.get(Identification, identification_id)
    if row is None or row.workspace_id != WORKSPACE:
        raise HTTPException(404, "Identification not found.")
    return row


def image_json(row: ItemImage) -> dict:
    return {"id": row.id, "item_id": row.item_id, "role": row.role, "width": row.width, "height": row.height,
            "crop": row.crop, "deleted": row.deleted_at is not None, "url": f"/api/images/{row.id}/content"}


def usage_json(u: AiUsage) -> dict:
    return {
        "id": u.id, "workspace_id": u.workspace_id, "item_id": u.item_id,
        "identification_id": u.identification_id, "provider": u.provider, "model": u.model,
        "is_live": u.is_live, "is_retry": u.is_retry, "is_second_look": u.is_second_look,
        "cache_hit": u.cache_hit, "prompt_version": u.prompt_version, "schema_version": u.schema_version,
        "preprocessing_version": u.preprocessing_version, "image_count": u.image_count,
        "image_dimensions": u.image_dimensions, "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens, "reasoning_tokens": u.reasoning_tokens,
        "reserved_cost": ai_ledger.dollars(u.reserved_micros),
        "actual_cost": None if u.actual_micros is None else ai_ledger.dollars(u.actual_micros),
        "charged_cost": ai_ledger.dollars(u.charged_micros), "state": u.state, "outcome": u.outcome,
        "error": u.error, "latency_ms": u.latency_ms, "created_at": iso(u.created_at),
    }


def identification_json(db: Session, row: Identification) -> dict:
    attempts = db.scalars(select(AiUsage).where(AiUsage.identification_id == row.id).order_by(AiUsage.id)).all()
    out = {
        "id": row.id, "item_id": row.item_id, "kind": row.kind, "parent_id": row.parent_id,
        "provider": row.provider, "model": row.model, "reasoning": row.reasoning, "is_live": row.is_live,
        "is_mock": not row.is_live, "from_cache": row.from_cache_of is not None,
        "outcome": row.outcome, "status": row.status, "ok": row.outcome == "OK",
        "result": row.result, "error": row.error, "image_ids": row.image_ids,
        "seller_text": row.seller_text, "created_at": iso(row.created_at),
        "versions": {"prompt": row.prompt_version, "schema": row.schema_version,
                     "preprocessing": row.preprocessing_version},
        "attempts": [usage_json(u) for u in attempts],
        "cost": ai_ledger.dollars(sum(u.charged_micros for u in attempts)),
        "disagreements": None,
    }
    if row.parent_id is not None and row.outcome == "OK":
        parent = db.get(Identification, row.parent_id)
        if parent is not None and parent.result:
            out["disagreements"] = vision_schema.disagreements(parent.result, row.result)
    return out


@app.get("/api/vision/status")
def vision_status(db: Session = Depends(get_db)) -> dict:
    settings = settings_service.load_settings(db)
    t = ai_ledger.totals(db, settings, WORKSPACE)
    return {
        **vision_service.mode(settings), "workspace_id": WORKSPACE,
        "primary_model": settings.vision_primary_model, "review_model": settings.vision_review_model,
        "allowance": ai_ledger.dollars(t.allowance_micros), "used": ai_ledger.dollars(t.charged_micros),
        "remaining": ai_ledger.dollars(t.remaining_micros),
        "unresolved_count": t.unresolved_count, "unresolved": ai_ledger.dollars(t.unresolved_micros),
        "max_cost_per_item": ai_ledger.dollars(ai_ledger.to_micros(settings.ai_max_cost_per_item)),
        "max_images": vision_images.MAX_IMAGES_PER_ITEM,
        "external_notice": ("Photos and the seller text you analyze are sent to OpenAI."
                            if settings.vision_provider == "openai"
                            else "Mock mode: nothing leaves this computer and no real identification happens."),
    }


@app.get("/api/vision/usage")
def vision_usage(limit: int = 50, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(AiUsage).where(AiUsage.workspace_id == WORKSPACE)
                      .order_by(AiUsage.id.desc()).limit(min(limit, 500))).all()
    return [usage_json(u) for u in rows]


class ResolveBody(BaseModel):
    billed: bool
    actual_cost: Decimal | None = Field(default=None, ge=0)


@app.post("/api/vision/usage/{usage_id}/resolve")
def resolve_usage(usage_id: int, body: ResolveBody, db: Session = Depends(get_db)) -> dict:
    """A person settles an attempt whose billing was uncertain, after checking the provider's usage page."""
    row = db.get(AiUsage, usage_id)
    if row is None or row.workspace_id != WORKSPACE:
        raise HTTPException(404, "Usage record not found.")
    actual = None if body.actual_cost is None else ai_ledger.to_micros(body.actual_cost)
    return usage_json(ai_ledger.resolve(db, row, billed=body.billed, actual_micros=actual))


@app.get("/api/items/{item_id}/images")
def list_images(item_id: int, db: Session = Depends(get_db)) -> list[dict]:
    return [image_json(r) for r in image_service.active_images(db, get_item_or_404(db, item_id).id)]


@app.post("/api/items/{item_id}/images")
def upload_image(item_id: int, file: UploadFile = File(...), role: str = Form("garment"),
                 db: Session = Depends(get_db)) -> dict:
    item = get_item_or_404(db, item_id)
    data = file.file.read(vision_images.MAX_UPLOAD_BYTES + 1)
    row = image_service.add_image(db, item, data, role)
    identity_service.sync(db, item, "A photo was added.")
    db.commit()
    return image_json(row)


class ImageUpdate(BaseModel):
    role: str
    crop: dict | None = None


@app.put("/api/images/{image_id}")
def update_image(image_id: int, body: ImageUpdate, db: Session = Depends(get_db)) -> dict:
    row = get_image_or_404(db, image_id)
    if row.deleted_at is not None:
        raise HTTPException(404, "This photo was deleted.")
    image_service.update_image(db, row, role=body.role, crop=body.crop)
    identity_service.sync(db, get_item_or_404(db, row.item_id), "A photo's crop or type was changed.")
    db.commit()
    return image_json(row)


@app.delete("/api/images/{image_id}")
def delete_image(image_id: int, db: Session = Depends(get_db)) -> dict:
    """Delete the photo file permanently. Past identifications keep only its hash."""
    row = get_image_or_404(db, image_id)
    if row.deleted_at is None:
        image_service.delete_image(db, row)
        identity_service.sync(db, get_item_or_404(db, row.item_id), "A photo was deleted.")
        db.commit()
    return {"deleted": image_id}


@app.get("/api/images/{image_id}/content")
def image_content(image_id: int, db: Session = Depends(get_db)) -> Response:
    row = get_image_or_404(db, image_id)
    try:
        data = image_service.read_file(row)
    except FileNotFoundError:
        raise HTTPException(404, "This photo is no longer stored.") from None
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


class IdentifyBody(BaseModel):
    image_ids: list[int] = Field(min_length=1, max_length=vision_images.MAX_IMAGES_PER_ITEM)
    seller_text: str = Field(default="", max_length=4000)


def _chosen_images(db: Session, item: Item, image_ids: list[int]) -> list[ItemImage]:
    active = {r.id: r for r in image_service.active_images(db, item.id)}
    if len(set(image_ids)) != len(image_ids) or any(i not in active for i in image_ids):
        raise HTTPException(400, "Choose photos that belong to this item and have not been deleted.")
    return [active[i] for i in image_ids]


@app.post("/api/items/{item_id}/identify/estimate")
def identify_estimate(item_id: int, body: IdentifyBody, db: Session = Depends(get_db)) -> dict:
    settings = settings_service.load_settings(db)
    item = get_item_or_404(db, item_id)
    provider = vision_service.get_provider(settings)
    return vision_service.estimate(db, settings, provider, item, _chosen_images(db, item, body.image_ids),
                                   body.seller_text)


@app.post("/api/items/{item_id}/identify")
def identify_item(item_id: int, body: IdentifyBody, db: Session = Depends(get_db)) -> dict:
    """Ask the configured vision provider for SUGGESTIONS. Confirms nothing."""
    settings = settings_service.load_settings(db)
    item = get_item_or_404(db, item_id)
    row = vision_service.identify(db, settings, item, _chosen_images(db, item, body.image_ids), body.seller_text)
    return identification_json(db, row)


@app.get("/api/items/{item_id}/identifications")
def list_identifications(item_id: int, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Identification).where(
        Identification.item_id == get_item_or_404(db, item_id).id, Identification.workspace_id == WORKSPACE)
        .order_by(Identification.id.desc()).limit(20)).all()
    return [identification_json(db, r) for r in rows]


def _second_look_inputs(db: Session, first: Identification) -> tuple[Item, list[ItemImage]]:
    if first.kind != "PRIMARY" or first.outcome != "OK":
        raise HTTPException(400, "A second look is only available for a completed first identification.")
    item = get_item_or_404(db, first.item_id)
    return item, _chosen_images(db, item, first.image_ids)


@app.get("/api/identifications/{identification_id}/second-look/estimate")
def second_look_estimate(identification_id: int, db: Session = Depends(get_db)) -> dict:
    settings = settings_service.load_settings(db)
    first = get_identification_or_404(db, identification_id)
    item, rows = _second_look_inputs(db, first)
    return vision_service.estimate(db, settings, vision_service.get_provider(settings), item, rows,
                                   first.seller_text, vision_service.SECOND_LOOK)


class SecondLookBody(BaseModel):
    # The maximum cost the person was shown and accepted, in micro-dollars.
    accepted_max_cost_micros: int = Field(ge=0)


@app.post("/api/identifications/{identification_id}/second-look")
def second_look(identification_id: int, body: SecondLookBody, db: Session = Depends(get_db)) -> dict:
    """Run the review model once, only on a person's request. Both answers are kept."""
    settings = settings_service.load_settings(db)
    first = get_identification_or_404(db, identification_id)
    item, rows = _second_look_inputs(db, first)
    provider = vision_service.get_provider(settings)
    est = vision_service.estimate(db, settings, provider, item, rows, first.seller_text, vision_service.SECOND_LOOK)
    if est["max_cost_micros"] > body.accepted_max_cost_micros:
        raise HTTPException(409, f"The estimated cost is now up to ${est['max_cost']}, more than you accepted. "
                                 f"Review the new estimate and ask again.")
    row = vision_service.identify(db, settings, item, rows, first.seller_text, parent=first, provider=provider)
    return identification_json(db, row)


class ConfirmBody(BaseModel):
    # The fingerprint of the details and photos the person reviewed.
    fingerprint: str
    identification_id: int | None = None


@app.post("/api/items/{item_id}/confirm-identity")
def confirm_identity(item_id: int, body: ConfirmBody, db: Session = Depends(get_db)) -> dict:
    """A PERSON confirms the item's current details and photos. Nothing else can."""
    item = get_item_or_404(db, item_id)
    identity_service.confirm(db, item, source="identify_page", expected_fingerprint=body.fingerprint,
                             identification_id=body.identification_id)
    db.commit()
    return item_json(item, db)


@app.post("/api/items/{item_id}/unconfirm-identity")
def unconfirm_identity(item_id: int, db: Session = Depends(get_db)) -> dict:
    item = get_item_or_404(db, item_id)
    identity_service.revoke(db, item, "Confirmation was withdrawn.")
    db.commit()
    return item_json(item, db)


# Serve the built web interface (frontend/dist) when it exists, so one
# command can run the whole application.
_dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="web")
