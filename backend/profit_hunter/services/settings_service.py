"""Load and save application settings (one JSON document in the database)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import Settings
from ..db.models import AppSetting
from . import to_db_time, utcnow

_KEY = "settings"


def load_settings(db: Session) -> Settings:
    """Saved settings, with defaults filling anything not yet saved."""
    row = db.get(AppSetting, _KEY)
    return Settings.model_validate(row.value) if row else Settings()


def save_settings(db: Session, settings: Settings) -> Settings:
    data = settings.model_dump(mode="json")  # Decimals become exact strings
    row = db.get(AppSetting, _KEY)
    if row:
        row.value, row.updated_at = data, to_db_time(utcnow())
    else:
        db.add(AppSetting(key=_KEY, value=data, updated_at=to_db_time(utcnow())))
    db.commit()
    return settings


def update_settings(db: Session, **changes) -> Settings:
    """Change some settings; everything is re-validated before saving."""
    current = load_settings(db).model_dump()
    unknown = set(changes) - set(current)
    if unknown:
        raise KeyError(f"Unknown setting(s): {', '.join(sorted(unknown))}")
    current.update(changes)
    return save_settings(db, Settings.model_validate(current))
