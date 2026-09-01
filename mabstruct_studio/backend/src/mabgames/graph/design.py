"""DESIGN — ported from the notebook, with one bug fixed.

The notebook formatted its prompt from `ideas[0]` but keyed the record to
`ideas[CHOSEN_IDEA_INDEX]`. Those agree only because the constant is `0`; set it
to anything else and the design would be written *for* one idea and *recorded
against* another. Binding `chosen` once makes that unexpressible.
"""

from collections.abc import Callable

from langchain.messages import HumanMessage

from mabgames.graph.models import GameDesignRecord
from mabgames.graph.prompts import DESIGN_HUMAN_PROMPT
from mabgames.graph.state import GameStudioState


def make_design_node(agent) -> Callable[[GameStudioState], dict]:
    def design_node(state: GameStudioState) -> dict:
        chosen = next(
            idea
            for idea in state["game_ideation"].ideas
            if idea.idea_id == state["chosen_idea_id"]
        )
        instruction = DESIGN_HUMAN_PROMPT.format(
            GAME_TITLE=state["game_title"], GAME_IDEA=chosen
        )
        agent_result = agent.invoke({"messages": [HumanMessage(content=instruction)]})
        return {
            "game_designs": [
                GameDesignRecord(
                    idea_id=chosen.idea_id,
                    brief=agent_result["structured_response"],
                )
            ]
        }

    return design_node
