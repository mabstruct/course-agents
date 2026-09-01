"""AD2 — the LangGraph pipeline, ported from `mabstruct_studio.ipynb`.

IDEATION -> SELECT (R2's human decision point) -> DESIGN. DEVELOP and DEPLOY
port into this same graph next; the notebook's model config, streaming
behaviour, retry middleware, chunked tool protocol and Tier-0 validation carry
over as-is when they do.

**Nothing here may import `mabgames.domain`.** These nodes are pure state
transformers so they stay runnable in the spike notebook; the API persists their
output by consuming the update stream. `tests/test_layering.py` enforces it.
"""

from mabgames.graph.models import (
    GameDesignBrief,
    GameDesignRecord,
    GameIdea,
    GameIdeaList,
)
from mabgames.graph.select_idea import SELECT_IDEA_INTERRUPT_KIND
from mabgames.graph.state import GameStudioState, initial_state
from mabgames.graph.studio import (
    DESIGN_NODE,
    IDEATION_NODE,
    SELECT_IDEA_NODE,
    STATE_TYPES,
    build_studio_graph,
    make_checkpointer,
)

__all__ = [
    "DESIGN_NODE",
    "GameDesignBrief",
    "GameDesignRecord",
    "GameIdea",
    "GameIdeaList",
    "GameStudioState",
    "IDEATION_NODE",
    "SELECT_IDEA_INTERRUPT_KIND",
    "SELECT_IDEA_NODE",
    "STATE_TYPES",
    "build_studio_graph",
    "initial_state",
    "make_checkpointer",
]
