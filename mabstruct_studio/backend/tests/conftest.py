import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from mabgames.domain import models  # noqa: F401  — imported so tables register


@pytest.fixture(name="session")
def session_fixture():
    """A fresh in-memory database per test.

    StaticPool keeps every connection pointed at the same in-memory database;
    without it SQLite hands out a new empty one per connection.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()
