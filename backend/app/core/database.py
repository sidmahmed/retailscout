"""Database engine and session dependency.

NullPool is deliberate: in production the API runs behind Supabase's
Supavisor transaction pooler (:6543), which does the pooling — a local
SQLAlchemy pool on top of it causes connection churn and errors.
See database-architecture.md §"Connections from Vercel".
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

_engine = None
_session_factory = None


def get_engine():
    global _engine, _session_factory
    if _engine is None:
        _engine = create_engine(
            get_settings().database_url,
            poolclass=NullPool,
            pool_pre_ping=True,
        )
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a session, always closes it."""
    get_engine()
    assert _session_factory is not None
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()
