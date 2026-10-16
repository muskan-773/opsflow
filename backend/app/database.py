"""Database engine, session factory, and the declarative base.

The engine uses ``pool_pre_ping`` so stale connections (e.g. after a DB
restart) are discarded before use, and a modest ``pool_size`` for the dev
server. Each request gets its own session via the ``get_db`` dependency,
which commits on success and rolls back on error, then always closes.
"""
from __future__ import annotations

from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

from .config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """Declarative base shared by all models."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yield a session, commit/rollback/close around the request."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Used by the startup hook and the seed script."""
    from . import models  # noqa: F401  ensure models are imported

    Base.metadata.create_all(bind=engine)
