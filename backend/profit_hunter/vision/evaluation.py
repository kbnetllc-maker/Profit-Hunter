"""Scoring for the real-image evaluation, and the monthly cost projection.

Pure functions. The scores are only meaningful when the predictions come
from a REAL model looking at REAL, hand-labelled photos. Scores computed
from the mock provider measure nothing about accuracy.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal

SPLITS = ("dev", "heldout")
CASE_TYPES = ("clear_label", "partial_logo", "similar_styles", "generic", "conflicting", "unidentifiable")


def norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").casefold())


def matches(predicted: str | None, truth: str | None, aliases: list[str] | None = None) -> bool:
    return bool(norm(predicted)) and norm(predicted) in {norm(truth), *(norm(a) for a in aliases or [])} - {""}


def validate_labels(examples: list[dict]) -> list[str]:
    """Problems that would make the evaluation unsound. Empty list = usable."""
    problems, seen, group_split = [], set(), {}
    for n, e in enumerate(examples, start=1):
        where = f"example {n} ({e.get('id', 'no id')})"
        if not e.get("id") or e["id"] in seen:
            problems.append(f"{where}: id is missing or repeated")
        seen.add(e.get("id"))
        if e.get("split") not in SPLITS:
            problems.append(f"{where}: split must be one of {SPLITS}")
        if e.get("case_type") not in CASE_TYPES:
            problems.append(f"{where}: case_type must be one of {CASE_TYPES}")
        if not 1 <= len(e.get("images") or []) <= 3:
            problems.append(f"{where}: needs 1 to 3 images")
        truth = e.get("truth")
        if not isinstance(truth, dict) or not isinstance(truth.get("identifiable"), bool):
            problems.append(f"{where}: truth.identifiable must be true or false")
        elif truth["identifiable"] and not truth.get("brand") and not truth.get("category"):
            problems.append(f"{where}: an identifiable example needs at least a brand or a category")
        # Near-duplicates (same garment, same listing) must stay in ONE split.
        group = e.get("group") or e.get("id")
        if group_split.setdefault(group, e.get("split")) != e.get("split"):
            problems.append(f"{where}: group '{group}' appears in both splits")
    return problems


@dataclass(frozen=True)
class Record:
    """One evaluated example: the label and what came back."""
    example: dict
    valid: bool                # a structured answer was returned
    status: str                # reviewed identification status, or "failed"
    brand: str | None
    brand_basis: str
    style: str | None
    style_basis: str
    latency_ms: int | None
    cost_micros: int           # every attempt for this example, failures included


def _asserted(value: str | None, basis: str) -> bool:
    return bool(value) and basis in ("observed", "inferred")   # a seller's claim relayed as such is not an assertion


def _rate(hits: int, total: int) -> float | None:
    return None if total == 0 else round(hits / total, 4)


def _percentile(values: list[int], q: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1)]


def score(records: list[Record]) -> dict:
    valid = [r for r in records if r.valid]
    t = lambda r: r.example["truth"]  # noqa: E731
    brand_known = [r for r in records if t(r).get("brand")]
    style_known = [r for r in records if t(r).get("style")]
    brand_ok = lambda r: matches(r.brand, t(r).get("brand"), t(r).get("brand_aliases"))  # noqa: E731
    style_ok = lambda r: matches(r.style, t(r).get("style"), t(r).get("style_aliases"))  # noqa: E731

    def unsupported(r: Record) -> bool:
        bad_brand = _asserted(r.brand, r.brand_basis) and not brand_ok(r)
        bad_style = _asserted(r.style, r.style_basis) and not style_ok(r)
        return bad_brand or bad_style

    def useful(r: Record) -> bool:
        return (r.valid and r.status == "ready_for_review" and t(r)["identifiable"] and not unsupported(r)
                and (brand_ok(r) if t(r).get("brand") else True))

    should_abstain = [r for r in records if not t(r)["identifiable"]]
    abstained = lambda r: r.valid and r.status != "ready_for_review" and not _asserted(r.brand, r.brand_basis)  # noqa: E731
    usable = sum(useful(r) for r in records)
    total_cost = sum(r.cost_micros for r in records)
    latencies = [r.latency_ms for r in valid if r.latency_ms is not None]
    return {
        "examples": len(records),
        "structured_output_validity": _rate(len(valid), len(records)),
        "brand_accuracy_when_brand_is_determinable": _rate(sum(brand_ok(r) for r in brand_known), len(brand_known)),
        "brand_precision_when_a_brand_is_asserted": _rate(
            sum(brand_ok(r) for r in valid if _asserted(r.brand, r.brand_basis)),
            sum(_asserted(r.brand, r.brand_basis) for r in valid)),
        "style_accuracy_when_style_is_determinable": _rate(sum(style_ok(r) for r in style_known), len(style_known)),
        "unsupported_specific_identification_rate": _rate(sum(unsupported(r) for r in valid), len(valid)),
        "correct_abstention_rate": _rate(sum(abstained(r) for r in should_abstain), len(should_abstain)),
        "useful_result_coverage": _rate(usable, len(records)),
        "latency_ms_p50": _percentile(latencies, 0.5), "latency_ms_p95": _percentile(latencies, 0.95),
        "mean_cost_per_example_usd": None if not records else round(total_cost / len(records) / 1e6, 6),
        "total_cost_usd": round(total_cost / 1e6, 6),
        "cost_per_usable_identification_usd": None if usable == 0 else round(total_cost / usable / 1e6, 6),
        "usable_identifications": usable,
    }


def monthly_cost(*, analyses: int, input_tokens: int, output_tokens: int, primary_in: Decimal,
                 primary_out: Decimal, review_in: Decimal, review_out: Decimal,
                 second_look_share: Decimal, failure_overhead: Decimal) -> Decimal:
    """Projected monthly vision cost in dollars. Prices are per million tokens.

    ``failure_overhead`` is the extra share of requests that are paid for but
    wasted (failed, truncated, or retried), e.g. 0.05 = 5%.
    """
    per_primary = (primary_in * input_tokens + primary_out * output_tokens) / 1_000_000
    per_review = (review_in * input_tokens + review_out * output_tokens) / 1_000_000
    requests = Decimal(analyses) * (1 + failure_overhead)
    return (requests * per_primary + requests * second_look_share * per_review).quantize(Decimal("0.01"))
