"""The studio graph: IDEATION -> SELECT -> DESIGN.

One graph, not three. The notebook ran DEVELOP and DEPLOY as separate single-node
graphs driven by hand-assembled state; those phases join this graph when they are
ported.
"""

import sqlite3
from pathlib import Path

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from mabgames.graph.agents import make_design_agent, make_ideation_agent
from mabgames.graph.design import make_design_node
from mabgames.graph.ideation import make_ideation_node
from mabgames.graph.models import (
    GameDesignBrief,
    GameDesignRecord,
    GameIdea,
    GameIdeaList,
)
from mabgames.graph.select_idea import select_idea_node
from mabgames.graph.state import GameStudioState

IDEATION_NODE = "ideation_node"
SELECT_IDEA_NODE = "select_idea_node"
DESIGN_NODE = "design_node"

# Pydantic objects living in graph state must be declared to the checkpoint
# serializer. Without this, langgraph warns on every checkpoint load that
# "Deserializing unregistered type ... will be blocked in a future version" —
# and that load is exactly R2's resume-days-later path.
#
# CAUTION: this pins module paths. Renaming or moving `graph/models.py` silently
# orphans every paused run.
STATE_TYPES = (GameIdeaList, GameIdea, GameDesignRecord, GameDesignBrief)


def make_checkpointer(path: Path | str) -> SqliteSaver:
    """The R2 checkpointer. Disposable, and separate from the domain DB (AD1).

    `check_same_thread=False` is safe here: SqliteSaver holds its own lock. It
    is needed because FastAPI runs sync handlers in a threadpool.
    """
    connection = sqlite3.connect(str(path), check_same_thread=False)
    return SqliteSaver(
        connection,
        serde=JsonPlusSerializer(allowed_msgpack_modules=list(STATE_TYPES)),
    )


def build_studio_graph(
    *,
    ideation_agent=None,
    design_agent=None,
    checkpointer=None,
):
    """Compile the graph.

    Agents are injected rather than imported at module scope — that is the test
    seam. Passing fakes exercises the *real* topology, interrupt and checkpointer
    while spending nothing, which is where all the risk in this slice lives.
    They are built inside this function, never at import (AD3).
    """
    builder = StateGraph(GameStudioState)

    builder.add_node(IDEATION_NODE, make_ideation_node(ideation_agent or make_ideation_agent()))
    builder.add_node(SELECT_IDEA_NODE, select_idea_node)
    builder.add_node(DESIGN_NODE, make_design_node(design_agent or make_design_agent()))

    builder.add_edge(START, IDEATION_NODE)
    builder.add_edge(IDEATION_NODE, SELECT_IDEA_NODE)
    builder.add_edge(SELECT_IDEA_NODE, DESIGN_NODE)
    builder.add_edge(DESIGN_NODE, END)

    return builder.compile(checkpointer=checkpointer)
