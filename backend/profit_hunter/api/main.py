"""Profit Hunter web API.

Start it with:  uvicorn profit_hunter.api.main:app --reload

All money travels as strings ("12.50") so nothing is ever rounded by a
browser. The browser only displays numbers; every calculation happens here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterator

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import init_db, make_engine, make_session_factory
from ..db.models import Analysis, Item, Purchase, SellerSession
from ..engine.max_bid import increment_at
from ..engine.profit import ProfitResult, PurchaseTerms, evaluate
from ..money import ZERO, from_cents, opt_from_cents
from ..services import (analysis_service, budget_service, sessions_service, settings_service,
                        to_db_time, utcnow)

app = FastAPI(title="Profit Hunter", version="0.1.0")
_factory = None


def get_db() -> Iterator[Session]:
    global _factory
    if _factory is None:
        engine = make_engine()
        init_db(engine)
        _factory = make_session_factory(engine)
    with _factory() as db:
        yield db


@app.exception_handler(budget_service.BudgetError)
async def _budget_error(_request, exc):
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
    return settings_service.save_settings(db, settings).model_dump(mode="json")


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
        expected_net_proceeds=body.expected_net_proceeds)
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


class AnalyzeRequest(BaseModel):
    session_id: int
    item: ItemDetails
    # Conservative expected sale price entered by the user. Leave empty when
    # there is no reliable evidence; the result is then SKIP.
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

    q = analysis_service.quote_bid(
        db, settings, session, expected_sale_price=body.expected_sale_price,
        id_confidence=None,  # AI identification arrives in Milestone 4
        manually_confirmed=body.item.manually_confirmed,
        valuation_is_lower_bound=body.valuation_is_lower_bound, current_bid=body.current_bid,
        marketplace=marketplace, authenticity_uncertain=body.authenticity_uncertain,
        suspected_counterfeit=body.suspected_counterfeit,
        condition_unverifiable=body.condition_unverifiable)

    terms = PurchaseTerms(inbound_shipping=q.shipping.amount, tax_rate=settings.purchase_tax_rate,
                          tax_applies_to_shipping=settings.tax_applies_to_shipping)
    sale_json = max_json = at_max = at_next = None
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

    item = Item(**body.item.model_dump(), created_at=to_db_time(utcnow()))
    db.add(item)
    db.flush()
    result = {
        "item": body.item.model_dump(),
        "session": {"id": session.id, "seller": session.seller.username},
        "is_simulated": session.is_simulated,
        "recommendation": q.decision.recommendation.value,
        "reasons": q.decision.reasons, "warnings": q.decision.warnings,
        "authorizes_purchase": False,
        "identification": {
            "confidence": None, "manually_confirmed": body.item.manually_confirmed,
            "required_confidence": str(settings.min_id_confidence),
            "evidence": ("Details confirmed by the user." if body.item.manually_confirmed
                         else "Not confirmed. No AI identification has been run."),
        },
        "valuation": {
            "source": "Entered manually by the user" if body.expected_sale_price else "None",
            "note": body.valuation_note, "is_lower_bound": body.valuation_is_lower_bound,
            "comparables_used": [], "comparables_excluded": [],
        },
        "sale": sale_json,
        "shipping": {"amount": money(q.shipping.amount), "is_estimate": q.shipping.is_estimate,
                     "basis": q.shipping.basis},
        "purchase_tax_rate": str(settings.purchase_tax_rate),
        "remaining_budget": money(q.remaining_budget),
        "seller_exposure_remaining": money(q.seller_exposure_remaining),
        "current_bid": money(body.current_bid), "next_bid": money(next_bid),
        "max_bid": max_json, "at_max_bid": at_max, "at_next_bid": at_next,
        "preferred_roi": str(settings.preferred_roi),
    }
    record = Analysis(
        item_id=item.id, session_id=session.id, is_simulated=session.is_simulated,
        recommendation=result["recommendation"],
        max_bid_cents=None if q.decision.max_bid is None else int(q.decision.max_bid * 100),
        inputs={"request": body.model_dump(mode="json"), "settings": settings.model_dump(mode="json")},
        result=result, created_at=to_db_time(utcnow()))
    db.add(record)
    db.commit()
    return {"id": record.id, "item_id": item.id, "created_at": iso(record.created_at), **result}


@app.get("/api/analyses")
def list_analyses(simulated: bool = False, limit: int = 25, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Analysis).where(Analysis.is_simulated == simulated)
                      .order_by(Analysis.id.desc()).limit(min(limit, 200))).all()
    return [{"id": a.id, "item_id": a.item_id, "created_at": iso(a.created_at), **a.result} for a in rows]


@app.get("/api/analyses/{analysis_id}")
def read_analysis(analysis_id: int, db: Session = Depends(get_db)) -> dict:
    a = db.get(Analysis, analysis_id)
    if a is None:
        raise HTTPException(404, "Analysis not found.")
    return {"id": a.id, "item_id": a.item_id, "created_at": iso(a.created_at), "inputs": a.inputs, **a.result}


# Serve the built web interface (frontend/dist) when it exists, so one
# command can run the whole application.
_dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="web")
