"""The FastAPI application.

Run it standalone:

    cd mabstruct_studio/backend
    ../../.venv/bin/python -m uvicorn mabgames.api.app:app --port 8000

Q5/AD3 chose self-hosted FastAPI *written so it can be mounted*: this same app
can be given to a LangGraph server through `langgraph.json`'s `http.app`, which
takes an import path to a Starlette/FastAPI application. That stays true only
while `create_app()` touches no engine, no model client and no filesystem —
every one of those hangs off a dependency instead, and startup work happens in
the lifespan handler. The module-level `app` below is just the import target.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from mabgames.api import deps, routes
from mabgames.domain.db import create_db_and_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Stands in for migrations while the schema is still moving.
    create_db_and_tables()
    deps.get_graph()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="MABSTRUCT Studio", lifespan=lifespan)
    app.include_router(routes.router, prefix="/api")
    return app


app = create_app()
