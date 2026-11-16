"""SQLite connection setup."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Repo-root/data/profit_hunter.db unless PROFIT_HUNTER_DB says otherwise.
DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / "data" / "profit_hunter.db"


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None) -> Engine:
    """Create the database engine. Use ``sqlite://`` for a throwaway in-memory database."""
    if url is None:
        path = Path(os.environ.get("PROFIT_HUNTER_DB", DEFAULT_DB_PATH))
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{path}"
    kwargs = {}
    if url in ("sqlite://", "sqlite:///:memory:"):
        from sqlalchemy.pool import StaticPool
        kwargs = {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
    engine = create_engine(url, **kwargs)

    @event.listens_for(engine, "connect")
    def _enforce_foreign_keys(dbapi_conn, _record):  # SQLite ignores FKs unless asked
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


def init_db(engine: Engine) -> None:
    """Create missing tables, then upgrade an older database in place.

    The upgrade only ADDS: new nullable columns and new indexes. It never
    drops, rewrites or re-creates anything, so existing rows are untouched.
    """
    from . import models  # noqa: F401  (registers the tables)
    Base.metadata.create_all(engine)
    existing = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            have = {c["name"] for c in existing.get_columns(table.name)}
            for column in table.columns:
                if column.name in have:
                    continue
                if not column.nullable:
                    raise RuntimeError(
                        f"Cannot add required column {table.name}.{column.name} to an existing "
                        f"database automatically. New columns must be optional.")
                kind = column.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {kind}'))
            for index in table.indexes:
                index.create(conn, checkfirst=True)


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)
