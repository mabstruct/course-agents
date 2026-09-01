from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from mabgames.api.app import create_app
from mabgames.api.deps import get_graph, session_dep
from mabgames.graph.studio import build_studio_graph, make_checkpointer
from fakes import FakeAgent, fake_brief, fake_ideas

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


@pytest.fixture(name="agents")
def agents_fixture():
    """The two fake phase agents, returned so tests can inspect their prompts."""
    return SimpleNamespace(
        ideation=FakeAgent(fake_ideas()),
        design=FakeAgent(fake_brief()),
    )


@pytest.fixture(name="graph")
def graph_fixture(agents):
    """The real graph and real interrupt, with fake agents and in-memory checkpoints."""
    return build_studio_graph(
        ideation_agent=agents.ideation,
        design_agent=agents.design,
        checkpointer=InMemorySaver(),
    )


@pytest.fixture(name="checkpoint_path")
def checkpoint_path_fixture(tmp_path):
    return tmp_path / "checkpoints.db"


@pytest.fixture(name="file_graph")
def file_graph_fixture(agents, checkpoint_path):
    """A graph over a real SQLite checkpoint file, for the restart test (R2)."""
    return build_studio_graph(
        ideation_agent=agents.ideation,
        design_agent=agents.design,
        checkpointer=make_checkpointer(checkpoint_path),
    )


@pytest.fixture(name="client")
def client_fixture(session, graph):
    """TestClient over the real app with the session and graph overridden."""
    app = create_app()
    app.dependency_overrides[session_dep] = lambda: session
    app.dependency_overrides[get_graph] = lambda: graph
    # No `with`: entering the context runs the lifespan, which would create the
    # real on-disk database and a real checkpoint file. Both are overridden here.
    yield TestClient(app)
    app.dependency_overrides.clear()
