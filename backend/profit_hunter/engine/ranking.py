"""Opportunity ranking: one transparent 0-100 score, not ROI alone.

Deterministic. The weights are PRELIMINARY ASSUMPTIONS to be calibrated
from real sales. Every component is reported so the score can be audited.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .valuation import MODERATE, STRONG, WEAK

WEIGHTS: dict[str, Decimal] = {
    "net_profit": Decimal(25),
    "roi": Decimal(20),
    "evidence_quality": Decimal(15),
    "capital_required": Decimal(10),
    "id_confidence": Decimal(10),
    "resale_speed": Decimal(10),
    "incremental_shipping": Decimal(5),
    "inventory_concentration": Decimal(5),
}
_EVIDENCE = {STRONG: Decimal("1"), MODERATE: Decimal("0.6"), WEAK: Decimal("0.3")}
_ONE, _ZERO = Decimal(1), Decimal(0)


@dataclass(frozen=True)
class RankInputs:
    net_profit: Decimal
    roi: Decimal | None
    all_in_cost: Decimal
    incremental_shipping: Decimal
    min_net_profit: Decimal
    preferred_roi: Decimal
    max_all_in_cost: Decimal
    id_confidence: Decimal  # 0..1 (1 when manually confirmed)
    evidence_quality: str | None  # None = price typed in by hand, no comparables
    holding_days: int | None
    max_holding_days: int
    category_share: Decimal  # share of this week's spending already in the same category, 0..1


@dataclass(frozen=True)
class RankScore:
    total: Decimal  # 0..100
    components: dict[str, Decimal]  # points earned per factor


def _clip(x: Decimal) -> Decimal:
    return max(_ZERO, min(_ONE, x))


def _ratio(n: Decimal, d: Decimal) -> Decimal:
    return _clip(n / d) if d > 0 else _ZERO


def rank(i: RankInputs) -> RankScore:
    fractions = {
        # Full marks at twice the minimum profit.
        "net_profit": _ratio(i.net_profit, 2 * i.min_net_profit),
        "roi": _ratio(i.roi or _ZERO, i.preferred_roi),
        "evidence_quality": _EVIDENCE.get(i.evidence_quality or "", _ZERO),
        "capital_required": _ONE - _ratio(i.all_in_cost, i.max_all_in_cost),
        "id_confidence": _clip(i.id_confidence),
        # Unknown time to sell earns nothing.
        "resale_speed": (_ZERO if i.holding_days is None
                         else _ONE - _ratio(Decimal(i.holding_days), Decimal(i.max_holding_days))),
        "incremental_shipping": _ONE - _ratio(i.incremental_shipping, i.all_in_cost),
        "inventory_concentration": _ONE - _clip(i.category_share),
    }
    q = Decimal("0.1")
    components = {k: (WEIGHTS[k] * f).quantize(q) for k, f in fractions.items()}
    return RankScore(sum(components.values(), _ZERO), components)
