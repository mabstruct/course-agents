"""DEVELOP — the expensive phase, ported from the notebook.

The agent never writes HTML into chat. It calls `write_game_html_part` in a
strict `start -> js x N -> end` sequence built by a per-build closure, and the
file only lands on disk on `end`.

Two behaviours are load-bearing and must not be "improved":

* **Exactly one repair turn on Tier-0 failure**, continuing the *same*
  conversation — never a second full build.
* **Failures are recorded, not raised.** A dead stream costs the turn, not the
  file already on disk, so `GameDevelopRecord.tier0_pass` plus `summary` carry
  the bad news onward.
"""

import logging
import uuid
from collections.abc import Callable
from pathlib import Path

from langchain.messages import HumanMessage

from mabgames.graph.agents import DEVELOP_RECURSION_LIMIT
from mabgames.graph.messages import message_text, tool_names_from_messages
from mabgames.graph.models import GameDevelopRecord
from mabgames.graph.paths import build_html_path
from mabgames.graph.prompts import DEVELOP_HUMAN_PROMPT
from mabgames.graph.state import GameStudioState
from mabgames.graph.tools.html_writer import make_dev_tools
from mabgames.graph.validation import run_static_validation

logger = logging.getLogger(__name__)


def make_develop_node(
    builds_dir: Path,
    agent_factory: Callable[[list], object],
    tools_factory: Callable[..., list] | None = None,
) -> Callable[[GameStudioState], dict]:
    """`agent_factory(tools) -> agent`.

    The agent cannot be pre-built and injected like ideation's and design's,
    because its tools are a closure over one build's id and buffer. The factory
    is the test seam instead.
    """
    tools_factory = tools_factory or make_dev_tools

    def develop_node(state: GameStudioState) -> dict:
        game_title = state["game_title"]
        chosen = next(
            idea
            for idea in state["game_ideation"].ideas
            if idea.idea_id == state["chosen_idea_id"]
        )
        design = next(
            record
            for record in state["game_designs"]
            if record.idea_id == chosen.idea_id
        )
        brief = design.brief

        # Minted here, before anything is written — the build owns its directory
        # and later its URL (Q4/AD5). The API persists the row under this id.
        build_id = str(uuid.uuid4())
        html_path = build_html_path(builds_dir, game_title, build_id)
        html_path.parent.mkdir(parents=True, exist_ok=True)
        # A fresh build id means nothing can be here, but a crashed half-write
        # from a retry of this very node could be.
        html_path.unlink(missing_ok=True)

        agent = agent_factory(tools_factory(builds_dir, game_title, build_id))
        instruction = DEVELOP_HUMAN_PROMPT.format(
            GAME_TITLE=game_title,
            IDEA_ID=chosen.idea_id,
            game_sub_title=brief.game_sub_title,
            game_genre=brief.game_genre,
            game_theme=brief.game_theme,
            game_style=brief.game_style,
            game_mood=brief.game_mood,
            game_description=brief.game_description,
            game_goal=brief.game_goal,
            game_objective=brief.game_objective,
            game_rules=brief.game_rules,
            game_controls=brief.game_controls,
            game_instructions=brief.game_instructions,
            game_mechanics=brief.game_mechanics,
            game_sound=brief.game_sound,
            game_art=brief.game_art,
            hints_for_the_team=brief.hints_for_the_team,
        )
        agent_config = {"recursion_limit": DEVELOP_RECURSION_LIMIT}

        def _run(messages):
            """One agent run. A dead stream costs the turn, not the file on disk."""
            try:
                return agent.invoke({"messages": messages}, config=agent_config)
            except Exception:
                # The only record that a model call died — the notebook printed
                # this, which made it invisible to anything but a terminal.
                logger.exception("develop invoke failed for build %s", build_id)
                return None

        def _validate() -> dict:
            return (
                run_static_validation(html_path)
                if html_path.exists()
                else {"pass": False, "issues": ["file not written"], "checks": {}}
            )

        agent_result = _run([HumanMessage(content=instruction)])
        validation = _validate()

        # One repair turn that continues the same conversation.
        if not validation["pass"] and agent_result is not None:
            note = (
                "Tier-0 validation failed: "
                + "; ".join(validation["issues"])
                + "\nRewrite the game from part=start, fixing those issues."
            )
            agent_result = _run(list(agent_result["messages"]) + [HumanMessage(content=note)])
            validation = _validate()

        messages = list(agent_result["messages"]) if agent_result else []
        summary = message_text(messages[-1]) if messages else "develop agent produced no messages"
        if not validation["pass"]:
            summary = (
                f"{summary}\n\nTier-0 issues: {'; '.join(validation['issues'])}\n"
                f"Tools called: {tool_names_from_messages(messages) or ['none']}"
            )

        return {
            "game_developments": [
                GameDevelopRecord(
                    idea_id=chosen.idea_id,
                    build_id=build_id,
                    html_path=str(html_path.resolve()),
                    tier0_pass=validation["pass"],
                    summary=summary,
                )
            ]
        }

    return develop_node
