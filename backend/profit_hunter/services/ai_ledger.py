"""The AI cost ledger: reserve before a call, reconcile after it.

Amounts are integer MICRO-DOLLARS (1,000,000 = $1). This ledger is the
operator's AI spending. It is entirely separate from the inventory budget.

The allowance never resets: every live row ever recorded counts against it.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..config import Settings, VisionPrice
from ..db.models import AiUsage
from . import to_db_time, utcnow

MICROS = 1_000_000


class NoPrice(Exception):
    """No price record covers the model, so a cost limit cannot be enforced."""


class AllowanceExceeded(Exception):
    pass


def to_micros(dollars: Decimal) -> int:
    return math.ceil(dollars * MICROS)


def dollars(micros: int) -> str:
    """Micro-dollars as a plain decimal string, e.g. 1234 -> '0.001234'."""
    return f"{Decimal(micros) / MICROS:.6f}"


def price_for(settings: Settings, model: str, on: date) -> VisionPrice:
    records = [p for p in settings.vision_prices if p.model == model and p.effective_from <= on]
    if not records:
        raise NoPrice(f"No price is recorded for model '{model}'. Add one in Settings before using it; "
                      f"without a price its cost cannot be limited.")
    return max(records, key=lambda p: p.effective_from)


def cost_micros(price: VisionPrice, input_tokens: int, output_tokens: int) -> int:
    # dollars per million tokens x tokens = micro-dollars, exactly.
    return math.ceil(price.input_per_million * input_tokens + price.output_per_million * output_tokens)


@dataclass(frozen=True)
class Totals:
    allowance_micros: int
    charged_micros: int  # reconciled costs plus open and unresolved reservations
    unresolved_micros: int
    unresolved_count: int

    @property
    def remaining_micros(self) -> int:
        return self.allowance_micros - self.charged_micros


def _sum(db: Session, workspace: str, *conditions) -> int:
    return db.scalar(select(func.coalesce(func.sum(AiUsage.charged_micros), 0)).where(
        AiUsage.workspace_id == workspace, AiUsage.is_live.is_(True), *conditions))


def totals(db: Session, settings: Settings, workspace: str) -> Totals:
    unresolved = db.execute(select(func.coalesce(func.sum(AiUsage.charged_micros), 0), func.count()).where(
        AiUsage.workspace_id == workspace, AiUsage.is_live.is_(True), AiUsage.state == "UNRESOLVED")).one()
    return Totals(to_micros(settings.ai_pilot_allowance), _sum(db, workspace), unresolved[0], unresolved[1])


def item_charged(db: Session, workspace: str, item_id: int) -> int:
    return _sum(db, workspace, AiUsage.item_id == item_id)


_RESERVE = text("""
INSERT INTO ai_usage (attempt_key, workspace_id, item_id, provider, model, is_live, is_retry, is_second_look,
                      cache_hit, prompt_version, schema_version, preprocessing_version, image_count,
                      image_dimensions, reserved_micros, charged_micros, state, outcome, error, created_at)
SELECT :key, :ws, :item, :provider, :model, 1, :is_retry, :is_second_look, 0, :prompt_version,
       :schema_version, :preprocessing_version, :image_count, :image_dimensions, :amount, :amount,
       'RESERVED', '', '', :now
WHERE (SELECT COALESCE(SUM(charged_micros), 0) FROM ai_usage
       WHERE workspace_id = :ws AND is_live = 1) + :amount <= :allowance
  AND (SELECT COALESCE(SUM(charged_micros), 0) FROM ai_usage
       WHERE workspace_id = :ws AND is_live = 1 AND item_id = :item) + :amount <= :item_cap
""")


def reserve(db: Session, settings: Settings, workspace: str, *, item_id: int, amount_micros: int,
            **columns) -> AiUsage:
    """Set aside ``amount_micros`` for one attempt, or raise AllowanceExceeded.

    The check and the insert are ONE SQL statement, so two requests at the
    same moment can never both take the last of the allowance.
    """
    import json
    db.commit()  # end any open read so the statement below starts its own write
    key = str(uuid.uuid4())
    params = {"key": key, "ws": workspace, "item": item_id, "amount": amount_micros,
              "allowance": to_micros(settings.ai_pilot_allowance),
              "item_cap": to_micros(settings.ai_max_cost_per_item),
              "now": to_db_time(utcnow()).strftime("%Y-%m-%d %H:%M:%S.%f"), **columns}
    params["image_dimensions"] = json.dumps(params.get("image_dimensions", []))
    inserted = db.execute(_RESERVE, params).rowcount
    db.commit()
    if inserted != 1:
        t = totals(db, settings, workspace)
        if amount_micros > t.remaining_micros:
            raise AllowanceExceeded(
                f"This request could cost up to ${dollars(amount_micros)}, but only "
                f"${dollars(max(t.remaining_micros, 0))} of the ${settings.ai_pilot_allowance} AI allowance is left. "
                f"Nothing was sent.")
        used = item_charged(db, workspace, item_id)
        raise AllowanceExceeded(
            f"This request could cost up to ${dollars(amount_micros)}. With ${dollars(used)} already used on "
            f"this item, that would pass the ${settings.ai_max_cost_per_item} limit per item. Nothing was sent.")
    return db.scalar(select(AiUsage).where(AiUsage.attempt_key == key))


def record_free(db: Session, workspace: str, *, state: str, **columns) -> AiUsage:
    """A row that costs nothing: a mock call, a cache hit or a blocked request."""
    row = AiUsage(attempt_key=str(uuid.uuid4()), workspace_id=workspace, state=state,
                  reserved_micros=0, charged_micros=0, created_at=to_db_time(utcnow()), **columns)
    db.add(row)
    db.commit()
    return row


def reconcile(db: Session, row: AiUsage, *, actual_micros: int | None, outcome: str, latency_ms: int,
              input_tokens: int | None = None, output_tokens: int | None = None,
              reasoning_tokens: int | None = None, error: str = "") -> None:
    """Replace the reservation with the real cost. With no usage reported the
    full reservation stays charged (the provider answered, so it billed)."""
    row.input_tokens, row.output_tokens, row.reasoning_tokens = input_tokens, output_tokens, reasoning_tokens
    row.actual_micros = actual_micros
    if row.is_live:
        row.charged_micros = row.reserved_micros if actual_micros is None else actual_micros
        row.state = "RECONCILED"
    row.outcome, row.error, row.latency_ms = outcome, error, latency_ms
    row.resolved_at = to_db_time(utcnow())
    db.commit()


def release(db: Session, row: AiUsage, *, outcome: str, error: str, latency_ms: int) -> None:
    """The provider definitely did not bill: free the reservation."""
    if row.is_live:
        row.charged_micros, row.state = 0, "RELEASED"
    row.outcome, row.error, row.latency_ms = outcome, error, latency_ms
    row.resolved_at = to_db_time(utcnow())
    db.commit()


def hold_unresolved(db: Session, row: AiUsage, *, error: str, latency_ms: int) -> None:
    """We cannot know whether the provider billed. Keep the money set aside
    until a person resolves it against the provider's own usage page."""
    if row.is_live:
        row.state = "UNRESOLVED"
    row.outcome, row.error, row.latency_ms = "UNCERTAIN", error, latency_ms
    db.commit()


def resolve(db: Session, row: AiUsage, *, billed: bool, actual_micros: int | None = None) -> AiUsage:
    """A person settles an UNRESOLVED attempt after checking the provider's records."""
    if row.state != "UNRESOLVED":
        raise ValueError("Only an unresolved attempt can be resolved.")
    if billed:
        row.actual_micros = row.reserved_micros if actual_micros is None else actual_micros
        row.charged_micros, row.state = row.actual_micros, "RECONCILED"
    else:
        row.charged_micros, row.state = 0, "RELEASED"
    row.resolved_at = to_db_time(utcnow())
    db.commit()
    return row
