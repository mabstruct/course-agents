"""The studio graph: IDEATION -> SELECT -> DESIGN -> APPROVE -> DEVELOP -> DEPLOY.

**One graph, not three.** The notebook ran DEVELOP and DEPLOY as separate
single-node graphs fed by hand-assembled state — which is why their node bodies
read shapes (`state["game_ideation"][0]`, a bare `GameDesignBrief`) that only
that state had. Wiring all four phases together is what reconciled those
accessors; both nodes now select by `chosen_idea_id`, never by index.

Two human decision points: SELECT (R2) chooses the idea, APPROVE gates the
expensive build.
"""

import sqlite3
from pathlib import Path

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from mabgames.config import get_settings
from mabgames.graph.agents import (
    make_deploy_agent,
    make_design_agent,
    make_develop_agent,
    make_ideation_agent,
)
from mabgames.graph.approve_build import approve_build_node
from mabgames.graph.deploy import make_deploy_node
from mabgames.graph.design import make_design_node
from mabgames.graph.develop import make_develop_node
from mabgames.graph.ideation import make_ideation_node
from mabgames.graph.models import (
    GameDeployRecord,
    GameDesignBrief,
    GameDesignRecord,
    GameDevelopRecord,
    GameIdea,
    GameIdeaList,
)
from mabgames.graph.select_idea import select_idea_node
from mabgames.graph.state import GameStudioState

IDEATION_NODE = "ideation_node"
SELECT_IDEA_NODE = "select_idea_node"
DESIGN_NODE = "design_node"
APPROVE_BUILD_NODE = "approve_build_node"
DEVELOP_NODE = "develop_node"
DEPLOY_NODE = "deploy_node"

# Pydantic objects living in graph state must be declared to the checkpoint
# serializer. Without this, langgraph warns on every checkpoint load that
# "Deserializing unregistered type ... will be blocked in a future version" —
# and that load is exactly R2's resume-days-later path.
#
# CAUTION: this pins module paths. Renaming or moving `graph/models.py` silently
# orphans every paused run.
STATE_TYPES = (
    GameIdeaList,
    GameIdea,
    GameDesignRecord,
    GameDesignBrief,
    GameDevelopRecord,
    GameDeployRecord,
)


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


def _build_gate(state: GameStudioState) -> str:
    """A rejected brief ends the run without a build. The idea stays `designed`."""
    return DEVELOP_NODE if state.get("build_approved") else END


def build_studio_graph(
    *,
    ideation_agent=None,
    design_agent=None,
    develop_agent_factory=None,
    deploy_agent_factory=None,
    dev_tools_factory=None,
    deploy_tools_factory=None,
    builds_dir=None,
    checkpointer=None,
):
    """Compile the graph.

    Agents are injected rather than imported at module scope — that is the test
    seam. Passing fakes exercises the *real* topology, interrupts and
    checkpointer while spending nothing, which is where all the risk lives.
    They are built inside this function, never at import (AD3).

    DEVELOP and DEPLOY take an agent *factory* rather than an agent, because
    their tools are closures over one build's id and buffer, so the agent cannot
    exist before the node runs.
    """
    builder = StateGraph(GameStudioState)
    builds_dir = builds_dir or get_settings().builds_dir

    builder.add_node(IDEATION_NODE, make_ideation_node(ideation_agent or make_ideation_agent()))
    builder.add_node(SELECT_IDEA_NODE, select_idea_node)
    builder.add_node(DESIGN_NODE, make_design_node(design_agent or make_design_agent()))
    builder.add_node(APPROVE_BUILD_NODE, approve_build_node)
    builder.add_node(
        DEVELOP_NODE,
        make_develop_node(
            builds_dir, develop_agent_factory or make_develop_agent, dev_tools_factory
        ),
    )
    builder.add_node(
        DEPLOY_NODE,
        make_deploy_node(
            builds_dir, deploy_agent_factory or make_deploy_agent, deploy_tools_factory
        ),
    )

    builder.add_edge(START, IDEATION_NODE)
    builder.add_edge(IDEATION_NODE, SELECT_IDEA_NODE)
    builder.add_edge(SELECT_IDEA_NODE, DESIGN_NODE)
    builder.add_edge(DESIGN_NODE, APPROVE_BUILD_NODE)
    builder.add_conditional_edges(APPROVE_BUILD_NODE, _build_gate, [DEVELOP_NODE, END])
    builder.add_edge(DEVELOP_NODE, DEPLOY_NODE)
    builder.add_edge(DEPLOY_NODE, END)

    return builder.compile(checkpointer=checkpointer)
