"""FastAPI dependencies.

AD3 keeps this app mountable: nothing is built at import time, so the same code
runs standalone under uvicorn or mounted into a LangGraph server via
`langgraph.json`'s `http.app`. The graph is a lazily-built singleton mirroring
`domain.db.get_engine` — which also means it works if a host mounts the app
without running its lifespan.
"""

import threading
from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends
from sqlmodel import Session

from mabgames.config import Settings, get_settings
from mabgames.domain.db import get_engine, get_session
from mabgames.graph.studio import build_studio_graph, make_checkpointer

_graph = None


def get_graph():
    global _graph
    if _graph is None:
        settings = get_settings()
        settings.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        _graph = build_studio_graph(checkpointer=make_checkpointer(settings.checkpoint_path))
    return _graph


def session_dep() -> Iterator[Session]:
    yield from get_session()


SessionDep = Annotated[Session, Depends(session_dep)]
GraphDep = Annotated[object, Depends(get_graph)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_session_factory() -> Callable[[], Session]:
    """A fresh session, for code that does not run inside a request.

    The background build needs its own: the request's session is closed by the
    time the thread runs, and `Session` is not thread-safe. Injected rather than
    imported so tests can hand back their in-memory one.
    """
    return lambda: Session(get_engine())


def get_task_runner() -> Callable[[Callable[[], None]], None]:
    """How long work leaves the request.

    Defaults to a daemon thread — no queue, no broker, no worker process, which
    is the right size for a single-operator studio. Tests override this with an
    inline runner, so the whole suite stays synchronous and only the thread
    itself goes untested.

    Rough edge, accepted: the thread dies with the process. A run interrupted
    mid-build sits at `developing` with a resumable checkpoint and no way to
    resume it over HTTP.
    """

    def run_in_thread(job: Callable[[], None]) -> None:
        threading.Thread(target=job, daemon=True).start()

    return run_in_thread


SessionFactoryDep = Annotated[Callable[[], Session], Depends(get_session_factory)]
TaskRunnerDep = Annotated[Callable[[Callable[[], None]], None], Depends(get_task_runner)]
