"""Database engine and session helpers (SQLAlchemy 2.0, synchronous).

Postgres in real use, SQLite for local development and tests.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base. Models arrive in Phase 2 (ticket #15) and Phase 1 (#8, #9)."""


def make_engine(url: str | None = None) -> Engine:
    url = url or get_settings().database_url
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool  # one shared connection so tests see their own data
    return create_engine(url, **kwargs)


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = make_engine()
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_session() -> Iterator[Session]:
    get_engine()
    assert _SessionLocal is not None
    with _SessionLocal() as session:
        yield session


def init_db() -> None:
    """Create tables if missing. Fine for development; real migrations come with Phase 2 (#15)."""
    from app import models  # noqa: F401  (registers the tables)

    Base.metadata.create_all(get_engine())


def reset_engine() -> None:
    """Forget the cached engine (used by tests)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def db_ok() -> bool:
    """True if the database answers a trivial query."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
