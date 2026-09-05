from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from mabgames.api.app import create_app
from mabgames.api.deps import get_graph, get_session_factory, get_task_runner, session_dep
from mabgames.graph.studio import build_studio_graph, make_checkpointer
from mabgames.graph.tools.deploy_tools import make_deploy_tools
from mabgames.graph.tools.herenow import HereNowClient
from fakes import (
    FakeAgent,
    FakeBuildAgent,
    FakeDeployAgent,
    FakeSession,
    fake_brief,
    fake_ideas,
    publish_responses,
)

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
        develop=FakeBuildAgent(),
        deploy=FakeDeployAgent(),
    )


@pytest.fixture(name="builds_dir")
def builds_dir_fixture(tmp_path):
    return tmp_path / "dev-output"


@pytest.fixture(name="herenow")
def herenow_fixture():
    """A here.now client over a stubbed transport.

    Injected into every test graph so no test can publish for real. An earlier
    version monkeypatched the module attribute and silently failed, because the
    node binds its tools factory when the graph is built — which is before the
    patch. Injection is the only version that actually holds.
    """
    return HereNowClient(api_key="test-key", session=FakeSession(publish_responses()))


@pytest.fixture(name="deploy_tools_factory")
def deploy_tools_factory_fixture(herenow):
    def factory(builds_dir, game_title, build_id, sub_title="", **kw):
        return make_deploy_tools(
            builds_dir, game_title, build_id, sub_title, client=herenow
        )

    return factory


@pytest.fixture(name="graph")
def graph_fixture(agents, builds_dir, deploy_tools_factory):
    """The real graph and real interrupts, with fake agents and in-memory checkpoints."""
    return build_studio_graph(
        ideation_agent=agents.ideation,
        design_agent=agents.design,
        develop_agent_factory=agents.develop,
        deploy_agent_factory=agents.deploy,
        deploy_tools_factory=deploy_tools_factory,
        builds_dir=builds_dir,
        checkpointer=InMemorySaver(),
    )


@pytest.fixture(name="checkpoint_path")
def checkpoint_path_fixture(tmp_path):
    return tmp_path / "checkpoints.db"


@pytest.fixture(name="file_graph")
def file_graph_fixture(agents, checkpoint_path, builds_dir, deploy_tools_factory):
    """A graph over a real SQLite checkpoint file, for the restart test (R2)."""
    return build_studio_graph(
        ideation_agent=agents.ideation,
        design_agent=agents.design,
        develop_agent_factory=agents.develop,
        deploy_agent_factory=agents.deploy,
        deploy_tools_factory=deploy_tools_factory,
        builds_dir=builds_dir,
        checkpointer=make_checkpointer(checkpoint_path),
    )


@pytest.fixture(name="client")
def client_fixture(session, graph):
    """TestClient over the real app with the session and graph overridden."""
    app = create_app()
    app.dependency_overrides[session_dep] = lambda: session
    app.dependency_overrides[get_graph] = lambda: graph
    # The background build runs inline in tests, so the suite stays synchronous
    # and every assertion sees a finished run. Only the thread goes untested.
    app.dependency_overrides[get_session_factory] = lambda: lambda: _KeepOpen(session)
    app.dependency_overrides[get_task_runner] = lambda: lambda job: job()
    # No `with`: entering the context runs the lifespan, which would create the
    # real on-disk database and a real checkpoint file. Both are overridden here.
    yield TestClient(app)
    app.dependency_overrides.clear()


class _KeepOpen:
    """Lends the test's session to code that wants to own one.

    The background build opens its own session via a context manager; in tests
    that has to be the same in-memory database, and closing it would end the test.
    """

    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *exc):
        return False
