"""Human confirmation of an item's identity, bound to exactly what was confirmed.

A confirmation covers one fingerprint: the item, its identity details and
its image set (including crops). Change any of them and the confirmation no
longer applies. Only a person's explicit action creates one; nothing a model
returns can.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import IdentityConfirmation, Item
from . import WORKSPACE, image_service, to_db_time, utcnow

IDENTITY_FIELDS = ("category", "brand", "model", "size", "color", "material", "era", "identifiers")


class IdentityChanged(Exception):
    pass


def _attributes(item: Item) -> dict:
    return {name: " ".join((getattr(item, name) or "").split()).casefold() for name in IDENTITY_FIELDS}


def _image_versions(db: Session, item: Item) -> list:
    return sorted([img.sha256, json.dumps(img.crop, sort_keys=True)] for img in image_service.active_images(db, item.id))


def fingerprint(db: Session, item: Item) -> str:
    payload = {"workspace": WORKSPACE, "item": item.id, "attributes": _attributes(item),
               "images": _image_versions(db, item)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _active(db: Session, item: Item) -> IdentityConfirmation | None:
    return db.scalar(select(IdentityConfirmation).where(
        IdentityConfirmation.item_id == item.id, IdentityConfirmation.workspace_id == WORKSPACE,
        IdentityConfirmation.revoked_at.is_(None)).order_by(IdentityConfirmation.id.desc()))


def is_confirmed(db: Session, item: Item) -> bool:
    active = _active(db, item)
    return bool(item.manually_confirmed and active and active.fingerprint == fingerprint(db, item))


def revoke(db: Session, item: Item, reason: str) -> bool:
    item.manually_confirmed = False
    active = _active(db, item)
    if active is None:
        return False
    active.revoked_at, active.revoke_reason = to_db_time(utcnow()), reason
    db.flush()
    return True


def confirm(db: Session, item: Item, *, source: str, expected_fingerprint: str | None = None,
            identification_id: int | None = None) -> IdentityConfirmation:
    """Record a person's confirmation of the item as it is right now.

    ``expected_fingerprint`` is what the person was looking at; if the item
    has changed since, the confirmation is refused.
    """
    db.flush()
    current = fingerprint(db, item)
    if expected_fingerprint is not None and expected_fingerprint != current:
        raise IdentityChanged("The item's details or photos changed since you reviewed them. "
                              "Review the current details and confirm again.")
    active = _active(db, item)
    if active is not None and active.fingerprint == current:
        item.manually_confirmed = True
        return active
    revoke(db, item, "Replaced by a newer confirmation.")
    row = IdentityConfirmation(
        workspace_id=WORKSPACE, item_id=item.id, identification_id=identification_id, fingerprint=current,
        attributes=_attributes(item), image_versions=_image_versions(db, item), source=source,
        confirmed_at=to_db_time(utcnow()))
    db.add(row)
    item.manually_confirmed = True
    db.flush()
    return row


def sync(db: Session, item: Item, reason: str) -> bool:
    """After any change to details or photos: drop a confirmation that no
    longer matches. Returns True when a confirmation was withdrawn."""
    db.flush()
    active = _active(db, item)
    if active is not None and active.fingerprint != fingerprint(db, item):
        return revoke(db, item, reason)
    if active is None and item.manually_confirmed:
        item.manually_confirmed = False  # a bare flag with nothing behind it is not a confirmation
        db.flush()
    return False


def state(db: Session, item: Item) -> dict:
    last = db.scalar(select(IdentityConfirmation).where(IdentityConfirmation.item_id == item.id)
                     .order_by(IdentityConfirmation.id.desc()))
    confirmed = is_confirmed(db, item)
    return {
        "confirmed": confirmed, "fingerprint": fingerprint(db, item),
        "confirmed_at": last.confirmed_at.isoformat() + "Z" if confirmed else None,
        "source": last.source if confirmed else None,
        "needs_reconfirmation": bool(last and not confirmed and last.revoked_at is not None),
        "last_revoke_reason": last.revoke_reason if last and last.revoked_at is not None else "",
    }
