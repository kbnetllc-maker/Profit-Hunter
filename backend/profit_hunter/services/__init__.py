"""Database-backed operations built on top of the pure engine."""

from datetime import datetime, timezone


# The single local workspace. Records and caches are scoped by this id so they
# can be separated per customer later. This is NOT access control.
WORKSPACE = "local"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_db_time(moment: datetime) -> datetime:
    """Store all times as naive UTC (SQLite has no timezone support)."""
    if moment.tzinfo is None:
        raise ValueError("A timezone-aware datetime is required.")
    return moment.astimezone(timezone.utc).replace(tzinfo=None)
