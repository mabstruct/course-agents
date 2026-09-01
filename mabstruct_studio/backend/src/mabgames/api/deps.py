"""FastAPI dependencies.

AD3 keeps this app mountable: nothing is built at import time, so the same code
runs standalone under uvicorn or mounted into a LangGraph server via
`langgraph.json`'s `http.app`. The graph is a lazily-built singleton mirroring
`domain.db.get_engine` — which also means it works if a host mounts the app
without running its lifespan.
"""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlmodel import Session

from mabgames.config import Settings, get_settings
from mabgames.domain.db import get_session
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
