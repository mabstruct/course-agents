"""R2 — the human decision point. Replaces the notebook's `CHOSEN_IDEA_INDEX`.

**This has to be its own node, after `ideation_node`.** An `interrupt()` inside
`ideation_node` would pause the graph before that node's state delta ever
streamed, so the API would have nothing persisted to show the human it is asking.
Splitting them is what makes R1 and R2 compose.
"""

from langgraph.types import interrupt

from mabgames.graph.state import GameStudioState

SELECT_IDEA_INTERRUPT_KIND = "select_idea"


def select_idea_node(state: GameStudioState) -> dict:
    """Pause, offer every idea, and record which one the human picked.

    The payload is plain JSON — never pydantic objects. It is handed to the
    browser verbatim and it is what gets checkpointed and re-read days later,
    so keeping it primitive keeps it out of the serializer allowlist entirely.
    """
    ideation = state["game_ideation"]
    choice = interrupt(
        {
            "kind": SELECT_IDEA_INTERRUPT_KIND,
            "game_title": state["game_title"],
            "ideas": [idea.model_dump() for idea in ideation.ideas],
        }
    )
    # A dict, so R4's DESIGN re-entry can add a note later without a shape change.
    # A bare string is tolerated so the notebook can resume with Command(resume=id).
    idea_id = choice["idea_id"] if isinstance(choice, dict) else str(choice)

    if idea_id not in {idea.idea_id for idea in ideation.ideas}:
        raise ValueError(f"resume names an idea that is not in this run: {idea_id}")

    return {"chosen_idea_id": idea_id}
