"""AD3 — the FastAPI service in front of the graph, and the layer that persists.

The graph nodes know nothing about the database. `lifecycle.py` consumes their
update stream and writes the domain rows, which is what keeps `graph/` runnable
in the spike notebook and every domain write in one place.
"""
