"""Engine and session handling.

AD3 keeps the API mountable, which means nothing here may run at import time and
nothing may assume it owns the process. The engine is built lazily; `get_session`
is written as a FastAPI dependency, and `create_db_and_tables` is called from a
lifespan handler rather than from module scope or `main`.
"""

from collections.abc import Iterator

from sqlalchemy import Engine
from sqlmodel import Session, SQLModel, create_engine

from mabgames.config import get_settings
from mabgames.domain import models  # noqa: F401  — imported so tables register

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            echo=settings.sql_echo,
            # SQLite refuses cross-thread use by default; FastAPI's threadpool
            # hands sessions to worker threads. Each request gets its own session.
            connect_args={"check_same_thread": False},
        )
    return _engine


def create_db_and_tables(engine: Engine | None = None) -> None:
    """Create any missing tables. Stands in for migrations while the schema moves."""
    SQLModel.metadata.create_all(engine or get_engine())


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    with Session(get_engine()) as session:
        yield session
