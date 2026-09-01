"""IDEATION — ported from the notebook.

Pure: it reads `game_title` and returns a state delta. It does not persist
anything. The API does that, by consuming this node's delta off the update
stream — which is what lets this node keep running unchanged in the notebook.
"""

import uuid
from collections.abc import Callable

from langchain.messages import HumanMessage

from mabgames.graph.models import GameIdeaList
from mabgames.graph.prompts import IDEATION_HUMAN_PROMPT
from mabgames.graph.state import GameStudioState


def make_ideation_node(agent) -> Callable[[GameStudioState], dict]:
    """The agent is injected so tests can run the real graph without an LLM."""

    def ideation_node(state: GameStudioState) -> dict:
        instruction = IDEATION_HUMAN_PROMPT.format(GAME_TITLE=state["game_title"])
        agent_result = agent.invoke({"messages": [HumanMessage(content=instruction)]})
        ideas = agent_result["structured_response"].ideas
        # The id is minted here, never by the LLM. Every later stage joins on it.
        tagged_ideas = [
            idea.model_copy(update={"idea_id": str(uuid.uuid4())}) for idea in ideas
        ]
        return {"game_ideation": GameIdeaList(ideas=tagged_ideas)}

    return ideation_node
