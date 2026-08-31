"""AD3 — the FastAPI service in front of the graph.

Empty for now. Q5 chose self-hosted FastAPI *written so it can be mounted*: the
same app must run standalone or be mounted into a LangGraph server via
`langgraph.json`'s `http.app`. That stays true only if nothing here assumes it
owns the process — DB session and settings arrive as dependencies, startup work
happens in a lifespan handler, and `main` does nothing.
"""
