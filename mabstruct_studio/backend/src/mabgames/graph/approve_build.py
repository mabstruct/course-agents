"""The build gate — a second human decision point, before the expensive phase.

R2 asks for one pause, before DESIGN. This is a second one, added deliberately:
DEVELOP runs Opus at 32k max_tokens for minutes, and a human who has just read
the design brief is the cheapest possible check on whether that spend is worth
making. Rejecting costs one design call instead of a whole build.

Rejecting leaves the idea at `designed`, which the derived status (R3) already
reports correctly — no new state, no new column.
"""

from langgraph.types import interrupt

from mabgames.graph.state import GameStudioState

APPROVE_BUILD_INTERRUPT_KIND = "approve_build"


def approve_build_node(state: GameStudioState) -> dict:
    """Pause with the design brief and wait for a go/no-go."""
    design = state["game_designs"][-1]
    decision = interrupt(
        {
            "kind": APPROVE_BUILD_INTERRUPT_KIND,
            "game_title": state["game_title"],
            "idea_id": design.idea_id,
            "brief": design.brief.model_dump(),
        }
    )
    approved = decision["approved"] if isinstance(decision, dict) else bool(decision)
    return {"build_approved": bool(approved)}
