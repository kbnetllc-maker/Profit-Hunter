"""Item images on disk. Files hold no metadata; rows outlive files for audit."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.base import DEFAULT_DB_PATH
from ..db.models import Item, ItemImage
from ..vision import images
from . import WORKSPACE, to_db_time, utcnow


def images_dir() -> Path:
    """PROFIT_HUNTER_IMAGES, or an ``images`` folder beside the database."""
    custom = os.environ.get("PROFIT_HUNTER_IMAGES")
    base = Path(custom) if custom else Path(os.environ.get("PROFIT_HUNTER_DB", DEFAULT_DB_PATH)).parent / "images"
    folder = base / WORKSPACE
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def active_images(db: Session, item_id: int) -> list[ItemImage]:
    return list(db.scalars(select(ItemImage).where(
        ItemImage.item_id == item_id, ItemImage.workspace_id == WORKSPACE, ItemImage.deleted_at.is_(None))
        .order_by(ItemImage.id)).all())


def _role(role: str) -> str:
    if role not in images.ROLES:
        raise images.ImageRejected(f"The photo type must be one of {', '.join(images.ROLES)}.")
    return role


def add_image(db: Session, item: Item, data: bytes, role: str) -> ItemImage:
    if len(active_images(db, item.id)) >= images.MAX_IMAGES_PER_ITEM:
        raise images.ImageRejected(f"An item can have at most {images.MAX_IMAGES_PER_ITEM} photos. Delete one first.")
    clean, width, height = images.clean_upload(data)
    name = f"{uuid.uuid4().hex}.jpg"  # never derived from the uploaded file name
    (images_dir() / name).write_bytes(clean)
    row = ItemImage(workspace_id=WORKSPACE, item_id=item.id, role=_role(role), filename=name, width=width,
                    height=height, sha256=images.sha256(clean), crop=None, created_at=to_db_time(utcnow()))
    db.add(row)
    db.flush()
    return row


def update_image(db: Session, row: ItemImage, *, role: str, crop: dict | None) -> ItemImage:
    row.role, row.crop = _role(role), images.validate_crop(crop)
    db.flush()
    return row


def read_file(row: ItemImage) -> bytes:
    if row.deleted_at is not None:
        raise FileNotFoundError("This photo was deleted.")
    return (images_dir() / row.filename).read_bytes()


def delete_image(db: Session, row: ItemImage) -> None:
    """Remove the file for good. The row keeps only size and hash, for audit."""
    (images_dir() / row.filename).unlink(missing_ok=True)
    row.deleted_at = to_db_time(utcnow())
    db.flush()
