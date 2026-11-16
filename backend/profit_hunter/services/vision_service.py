"""Run one identification: cache, cost reservation, provider call, reconciliation.

This service produces evidence and suggested attributes ONLY. It never
confirms an identity, never touches the inventory budget and never changes
a recommendation.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..db.models import Identification, Item, ItemImage
from ..vision import images, openai_provider, prompt, schema
from ..vision.mock import MockProvider
from ..vision.provider import OK, PreparedImage, ProviderError, VisionProvider, VisionRequest
from . import WORKSPACE, ai_ledger, image_service, to_db_time, utcnow, valuation_service

PRIMARY, SECOND_LOOK = "PRIMARY", "SECOND_LOOK"
_SCHEMA_CHARS = len(json.dumps(schema.IdentificationOutput.model_json_schema()))


class VisionUnavailable(Exception):
    """Identification cannot run right now. Manual entry still works."""


def mode(settings: Settings) -> dict:
    live = settings.vision_provider == "openai"
    key = openai_provider.api_key_present()
    ready = (not live) or (settings.vision_live_enabled and key)
    why = ""
    if live and not settings.vision_live_enabled:
        why = "Live AI calls are switched off in Settings."
    elif live and not key:
        why = f"No API key is set on the server ({openai_provider.API_KEY_ENV})."
    return {"mode": "live" if live else "mock", "provider": settings.vision_provider, "ready": bool(ready),
            "not_ready_reason": why, "live_enabled": settings.vision_live_enabled, "api_key_present": key}


def get_provider(settings: Settings) -> VisionProvider:
    if settings.vision_provider == "mock":
        return MockProvider(review_model=settings.vision_review_model)
    state = mode(settings)
    if not state["ready"]:
        raise VisionUnavailable(state["not_ready_reason"] + " You can still enter the details yourself.")
    try:
        return openai_provider.OpenAIProvider()
    except openai_provider.NotConfigured as exc:
        raise VisionUnavailable(str(exc)) from exc


@dataclass(frozen=True)
class Plan:
    kind: str
    model: str
    reasoning: str
    max_output_tokens: int
    prepared: tuple[PreparedImage, ...]
    image_ids: tuple[int, ...]
    seller_text: str
    user_text: str
    cache_key: str
    input_tokens_estimate: int
    reserve_micros: int  # upper bound for ONE attempt; 0 when the provider does not bill


def _prepare(settings: Settings, rows: list[ItemImage]) -> tuple[PreparedImage, ...]:
    if not 1 <= len(rows) <= images.MAX_IMAGES_PER_ITEM:
        raise ValueError(f"Choose between 1 and {images.MAX_IMAGES_PER_ITEM} photos to analyze.")
    out = []
    for row in rows:
        data, w, h, digest = images.prepare(image_service.read_file(row), row.crop, settings.vision_image_max_side)
        out.append(PreparedImage(data, w, h, digest, row.role))
    return tuple(out)


def plan(settings: Settings, provider: VisionProvider, rows: list[ItemImage], seller_text: str,
         kind: str = PRIMARY) -> Plan:
    review = kind == SECOND_LOOK
    model = settings.vision_review_model if review else settings.vision_primary_model
    reasoning = settings.vision_review_reasoning if review else settings.vision_primary_reasoning
    max_out = settings.vision_review_max_output_tokens if review else settings.vision_primary_max_output_tokens
    prepared = _prepare(settings, rows)
    seller = " ".join(seller_text.split())
    text = prompt.user_text([p.role for p in prepared], seller)
    key = hashlib.sha256(json.dumps([
        WORKSPACE, provider.name, model, reasoning, prompt.PROMPT_VERSION, schema.SCHEMA_VERSION,
        images.PREPROCESSING_VERSION, [[p.role, p.sha256] for p in prepared], seller]).encode()).hexdigest()

    image_tok = sum(images.image_tokens(p.width, p.height, settings.vision_image_token_multiplier) for p in prepared)
    text_tok = math.ceil((len(prompt.INSTRUCTIONS) + len(text) + _SCHEMA_CHARS) / 3)  # 3 chars per token: high side
    input_estimate = math.ceil((image_tok + text_tok) * settings.vision_reservation_safety_factor)
    reserve = 0
    if provider.bills:
        price = ai_ledger.price_for(settings, model, valuation_service.today_for(settings))
        reserve = ai_ledger.cost_micros(price, input_estimate, max_out)
    return Plan(kind, model, reasoning, max_out, prepared, tuple(r.id for r in rows), seller, text, key,
                input_estimate, reserve)


def _cached(db: Session, key: str) -> Identification | None:
    return db.scalar(select(Identification).where(
        Identification.workspace_id == WORKSPACE, Identification.cache_key == key,
        Identification.outcome == OK, Identification.from_cache_of.is_(None)).order_by(Identification.id.desc()))


def estimate(db: Session, settings: Settings, provider: VisionProvider, item: Item, rows: list[ItemImage],
             seller_text: str, kind: str = PRIMARY) -> dict:
    """What an analysis could cost, shown BEFORE anything is sent."""
    p = plan(settings, provider, rows, seller_text, kind)
    cached = _cached(db, p.cache_key) is not None
    one = 0 if cached else p.reserve_micros
    t = ai_ledger.totals(db, settings, WORKSPACE)
    item_used = ai_ledger.item_charged(db, WORKSPACE, item.id)
    item_cap = ai_ledger.to_micros(settings.ai_max_cost_per_item)
    return {
        "kind": kind, "model": p.model, "bills": provider.bills, "cached": cached,
        "max_cost_micros": one, "max_cost": ai_ledger.dollars(one),
        "max_cost_with_retry": ai_ledger.dollars(one * (1 + settings.vision_max_retries)),
        "input_tokens_estimate": p.input_tokens_estimate, "max_output_tokens": p.max_output_tokens,
        "item_spent": ai_ledger.dollars(item_used), "item_limit": ai_ledger.dollars(item_cap),
        "allowed": (not provider.bills) or cached or (one <= t.remaining_micros and item_used + one <= item_cap),
    }


def _row(db: Session, item: Item, p: Plan, provider: VisionProvider, *, parent: Identification | None,
         outcome: str, status: str, result: dict | None, error: str = "",
         from_cache_of: int | None = None) -> Identification:
    row = Identification(
        workspace_id=WORKSPACE, item_id=item.id, kind=p.kind, parent_id=parent.id if parent else None,
        provider=provider.name, model=p.model, reasoning=p.reasoning, prompt_version=prompt.PROMPT_VERSION,
        schema_version=schema.SCHEMA_VERSION, preprocessing_version=images.PREPROCESSING_VERSION,
        image_ids=list(p.image_ids), image_hashes=[i.sha256 for i in p.prepared], seller_text=p.seller_text,
        cache_key=p.cache_key, from_cache_of=from_cache_of, is_live=provider.bills, outcome=outcome,
        status=status, result=result, error=error, created_at=to_db_time(utcnow()))
    db.add(row)
    db.commit()
    return row


def identify(db: Session, settings: Settings, item: Item, rows: list[ItemImage], seller_text: str, *,
             parent: Identification | None = None, provider: VisionProvider | None = None) -> Identification:
    """One identification (or, with ``parent``, a second look at the same evidence).

    At most one retry, only after a transient failure and only when the
    allowance covers a fresh reservation. Failures are stored as failures.
    """
    provider = provider or get_provider(settings)
    p = plan(settings, provider, rows, seller_text, SECOND_LOOK if parent else PRIMARY)
    common = dict(item_id=item.id, provider=provider.name, model=p.model, is_second_look=parent is not None,
                  prompt_version=prompt.PROMPT_VERSION, schema_version=schema.SCHEMA_VERSION,
                  preprocessing_version=images.PREPROCESSING_VERSION, image_count=len(p.prepared),
                  image_dimensions=[[i.width, i.height] for i in p.prepared])

    hit = _cached(db, p.cache_key)
    if hit is not None:
        row = _row(db, item, p, provider, parent=parent, outcome=OK, status=hit.status, result=hit.result,
                   from_cache_of=hit.id)
        ai_ledger.record_free(db, WORKSPACE, state="NO_CHARGE", is_live=provider.bills, cache_hit=True,
                              outcome=OK, identification_id=row.id, latency_ms=0, **common)
        return row

    request = VisionRequest(p.model, p.reasoning, p.max_output_tokens, prompt.INSTRUCTIONS, p.user_text,
                            p.prepared, settings.vision_timeout_seconds)
    usage_rows, result, failure, uncertain = [], None, "No attempt was made.", False
    for attempt in range(1 + settings.vision_max_retries):
        if provider.bills:
            try:
                usage = ai_ledger.reserve(db, settings, WORKSPACE, amount_micros=p.reserve_micros,
                                          is_retry=attempt > 0, **common)
            except ai_ledger.AllowanceExceeded as exc:
                if attempt == 0:
                    ai_ledger.record_free(db, WORKSPACE, state="BLOCKED", is_live=True, outcome="BLOCKED",
                                          error=str(exc), **common)
                    raise
                failure += " No retry: the remaining AI allowance does not cover one."
                break
        else:
            usage = ai_ledger.record_free(db, WORKSPACE, state="NO_CHARGE", is_live=False,
                                          is_retry=attempt > 0, **common)
        usage_rows.append(usage)
        started = time.monotonic()
        try:
            result = provider.identify(request)
        except ProviderError as exc:
            ms = round((time.monotonic() - started) * 1000)
            failure, uncertain = str(exc), exc.may_have_billed
            if exc.may_have_billed:
                ai_ledger.hold_unresolved(db, usage, error=failure, latency_ms=ms)
            else:
                ai_ledger.release(db, usage, outcome="ERROR", error=failure, latency_ms=ms)
            if exc.transient:
                continue
            break
        except openai_provider.NotConfigured as exc:
            ai_ledger.release(db, usage, outcome="ERROR", error=str(exc),
                              latency_ms=round((time.monotonic() - started) * 1000))
            failure = str(exc)
            break
        ms = round((time.monotonic() - started) * 1000)
        actual = None
        if result.usage is not None and provider.bills:
            price = ai_ledger.price_for(settings, p.model, valuation_service.today_for(settings))
            actual = ai_ledger.cost_micros(price, result.usage.input_tokens, result.usage.output_tokens)
        u = result.usage
        ai_ledger.reconcile(db, usage, actual_micros=actual, outcome=result.outcome, latency_ms=ms,
                            input_tokens=u.input_tokens if u else None,
                            output_tokens=u.output_tokens if u else None,
                            reasoning_tokens=u.reasoning_tokens if u else None, error=result.detail)
        break

    if result is None:
        outcome = "UNCERTAIN" if uncertain else "ERROR"
        row = _row(db, item, p, provider, parent=parent, outcome=outcome, status="failed", result=None, error=failure)
    elif result.outcome != OK or result.output is None:
        row = _row(db, item, p, provider, parent=parent, outcome=result.outcome if result.outcome != OK else "EMPTY",
                   status="failed", result=None, error=result.detail or "The provider returned no usable answer.")
    elif result.model and not result.model.startswith(p.model):
        row = _row(db, item, p, provider, parent=parent, outcome="INVALID", status="failed", result=None,
                   error=f"Asked for model '{p.model}' but '{result.model}' answered. The answer was discarded.")
    else:
        reviewed = schema.review(result.output, image_count=len(p.prepared), has_seller_text=bool(p.seller_text))
        row = _row(db, item, p, provider, parent=parent, outcome=OK, status=reviewed["status"], result=reviewed)
    for usage in usage_rows:
        usage.identification_id = row.id
    db.commit()
    return row
