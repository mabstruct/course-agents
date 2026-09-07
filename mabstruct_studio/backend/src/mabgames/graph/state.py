"""The state that flows through the studio graph.

Trimmed to what this slice uses. Adding DEVELOP's and DEPLOY's channels back is
safe and costs nothing: resuming an existing checkpoint on a *widened* state was
verified to work, with the new channels arriving as their empty defaults. Four
unused fields in the first file anyone opens is the worse trade.

`chosen_idea_id` replaces the notebook's hand-edited `CHOSEN_IDEA_INDEX` (R2).

`refurb_of` + `refurb_feedback` are R4's DEVELOP re-entry. Both are primitives
(a str and a list of str), so the serializer allowlist does not grow.
"""

import operator
from typing import Annotated, TypedDict

from mabgames.graph.models import (
    GameDeployRecord,
    GameDesignBrief,
    GameDesignRecord,
    GameDevelopRecord,
    GameIdea,
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
    # R4 — set only on a refurb run. `refurb_of` is the build being patched and
    # routes the graph straight to DEVELOP; `refurb_feedback` is what the human
    # said about it, one line per feedback row.
    refurb_of: str | None
    refurb_feedback: list[str]


def initial_state(game_title: str) -> GameStudioState:
    return {
        "game_title": game_title,
        "game_ideation": None,
        "chosen_idea_id": None,
        "build_approved": None,
        "game_designs": [],
        "game_developments": [],
        "game_deployments": [],
        "refurb_of": None,
        "refurb_feedback": [],
    }


def refurb_state(
    game_title: str,
    idea: GameIdea,
    brief: GameDesignBrief,
    *,
    refurb_of: str,
    feedback: list[str],
) -> GameStudioState:
    """R4 DEVELOP-patch: the state a run would have had at the build gate.

    Same idea, same brief, approval implied — the human already asked for the
    refurb. The graph enters at DEVELOP and runs DEVELOP -> DEPLOY as usual.
    """
    return {
        "game_title": game_title,
        "game_ideation": GameIdeaList(ideas=[idea]),
        "chosen_idea_id": idea.idea_id,
        "build_approved": True,
        "game_designs": [GameDesignRecord(idea_id=idea.idea_id, brief=brief)],
        "game_developments": [],
        "game_deployments": [],
        "refurb_of": refurb_of,
        "refurb_feedback": list(feedback),
    }
