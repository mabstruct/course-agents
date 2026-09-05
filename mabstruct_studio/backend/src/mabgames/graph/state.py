"""The state that flows through the studio graph.

Trimmed to what this slice uses. Adding DEVELOP's and DEPLOY's channels back is
safe and costs nothing: resuming an existing checkpoint on a *widened* state was
verified to work, with the new channels arriving as their empty defaults. Four
unused fields in the first file anyone opens is the worse trade.

`chosen_idea_id` replaces the notebook's hand-edited `CHOSEN_IDEA_INDEX` (R2).
"""

import operator
from typing import Annotated, TypedDict

from mabgames.graph.models import (
    GameDeployRecord,
    GameDesignRecord,
    GameDevelopRecord,
    GameIdeaList,
)


class GameStudioState(TypedDict):
    """The development state of the game studio."""

    game_title: str
    game_ideation: GameIdeaList | None
    chosen_idea_id: str | None
    build_approved: bool | None
    # operator.add so parallel workers can append without clobbering (R7, later).
    # Rough edge: replaying a node appends rather than replaces, so a resumed
    # segment can leave a duplicate record here. The DB rows stay correct.
    game_designs: Annotated[list[GameDesignRecord], operator.add]
    game_developments: Annotated[list[GameDevelopRecord], operator.add]
    game_deployments: Annotated[list[GameDeployRecord], operator.add]


def initial_state(game_title: str) -> GameStudioState:
    return {
        "game_title": game_title,
        "game_ideation": None,
        "chosen_idea_id": None,
        "build_approved": None,
        "game_designs": [],
        "game_developments": [],
        "game_deployments": [],
    }
