"""The structured answer a vision model must return, and the deterministic
review applied to it before anything is shown or stored.

There is deliberately NO confidence percentage and NO price field. A model
cannot unlock BUY, and cannot supply a valuation.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

SCHEMA_VERSION = "id-schema-1"

Basis = Literal["observed", "inferred", "user_supplied", "unknown"]
Status = Literal["ready_for_review", "more_evidence_needed", "unable_to_identify"]
FIELDS = ("category", "brand", "style", "size", "color", "pattern", "material")
# These may only be reported when read from the item or stated by the user.
EXPLICIT_ONLY = ("size", "material")


class Finding(BaseModel):
    value: str | None
    basis: Basis
    evidence_source: str | None  # "image_1".."image_3" or "seller_text"
    evidence: str


class Defect(BaseModel):
    description: str
    evidence_source: str


class Variation(BaseModel):
    name: str
    distinguishing_evidence: str  # what would tell this variation apart


class Conflict(BaseModel):
    field: str
    description: str


class IdentificationOutput(BaseModel):
    status: Status
    summary: str
    category: Finding
    brand: Finding
    style: Finding
    size: Finding
    color: Finding
    pattern: Finding
    material: Finding
    label_text: list[str]
    visible_defects: list[Defect]
    possible_variations: list[Variation]
    conflicts: list[Conflict]
    missing_information: list[str]
    suggested_search_terms: list[str]
    another_photo_needed: bool
    photo_request: str | None


_AUTHENTICITY = re.compile(r"\b(authentic|genuine|legit(imate)?|not\s+(a\s+)?(fake|counterfeit)|real\s+deal)\b", re.I)
_PRICE = re.compile(r"[$€£]\s?\d|\b\d+(\.\d+)?\s?(usd|dollars?|bucks)\b|\b(resale|market)\s+(value|price)\b|\bworth\b", re.I)


def _texts(o: IdentificationOutput) -> list[str]:
    out = [o.summary, o.photo_request or "", *o.label_text, *o.missing_information]
    for name in FIELDS:
        f: Finding = getattr(o, name)
        out += [f.value or "", f.evidence]
    out += [d.description for d in o.visible_defects]
    out += [f"{v.name} {v.distinguishing_evidence}" for v in o.possible_variations]
    out += [c.description for c in o.conflicts]
    return out


def review(o: IdentificationOutput, *, image_count: int, has_seller_text: bool) -> dict:
    """Apply the rules a model cannot be trusted to follow. Returns plain data."""
    notes: list[str] = []
    valid_sources = {f"image_{i}" for i in range(1, image_count + 1)}
    if has_seller_text:
        valid_sources.add("seller_text")
    disputed = {c.field.strip().lower() for c in o.conflicts}

    fields: dict[str, dict] = {}
    for name in FIELDS:
        f: Finding = getattr(o, name)
        value = (f.value or "").strip() or None
        basis, source = f.basis, f.evidence_source
        if value is None or basis == "unknown":
            value, basis, source = None, "unknown", None
        elif source not in valid_sources:
            notes.append(f"{name}: the cited evidence source does not exist, so this is treated as a guess.")
            basis, source = "inferred", None
        elif source == "seller_text" and basis == "observed":
            basis = "user_supplied"  # a seller's statement is never an observation
        if value is not None and name in EXPLICIT_ONLY and basis == "inferred":
            notes.append(f"{name}: removed because it was guessed, not read from the item or supplied by you.")
            value, basis, source = None, "unknown", None
        fields[name] = {"value": value, "basis": basis, "evidence_source": source,
                        "evidence": f.evidence.strip() if value is not None else "",
                        "disputed": name in disputed and value is not None}

    terms = [t.strip() for t in o.suggested_search_terms if t.strip()]
    clean_terms = [t for t in terms if not _PRICE.search(t)]
    texts = _texts(o) + terms
    if any(_AUTHENTICITY.search(t) for t in texts):
        notes.append("The response comments on authenticity. A photo cannot establish authenticity; "
                     "treat this as unverified and use the risk checks.")
    if any(_PRICE.search(t) for t in texts):
        notes.append("The response mentions a price or value. It is ignored: prices come only from "
                     "comparables you enter.")

    known = [n for n in FIELDS if fields[n]["value"] is not None]
    status = o.status
    if not known and not o.label_text:
        status = "unable_to_identify"
    elif status == "ready_for_review" and not (fields["category"]["value"] and fields["brand"]["value"]):
        status = "more_evidence_needed"
        notes.append("Category or brand is unknown, so this is not ready for review.")
    if any(fields[n]["disputed"] for n in FIELDS) and status == "ready_for_review":
        status = "more_evidence_needed"
        notes.append("The evidence conflicts on at least one detail. Resolve it yourself before confirming.")

    return {
        "status": status, "summary": o.summary.strip(), "fields": fields,
        "label_text": [t.strip() for t in o.label_text if t.strip()],
        "visible_defects": [d.model_dump() for d in o.visible_defects],
        "possible_variations": [v.model_dump() for v in o.possible_variations],
        "conflicts": [c.model_dump() for c in o.conflicts],
        "missing_information": [m.strip() for m in o.missing_information if m.strip()],
        "suggested_search_terms": clean_terms,
        "another_photo_needed": o.another_photo_needed,
        "photo_request": (o.photo_request or "").strip() or None,
        "notes": notes,
    }


def disagreements(first: dict, second: dict) -> list[dict]:
    """Where two reviewed identifications differ. Agreement is NOT proof of correctness."""
    out = []
    if first["status"] != second["status"]:
        out.append({"field": "status", "first": first["status"], "second": second["status"]})
    for name in FIELDS:
        a, b = first["fields"][name]["value"], second["fields"][name]["value"]
        if (a or "").strip().casefold() != (b or "").strip().casefold():
            out.append({"field": name, "first": a, "second": b})
    return out
