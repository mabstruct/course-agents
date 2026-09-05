"""DEPLOY — publish the build to here.now, ported from the notebook.

Two properties carry over unchanged:

* **The Tier-0 gate is deterministic, not the agent's call.** A build that failed
  validation records a skipped deploy rather than raising.
* **The registry, not the agent's summary, says what went live.** An agent can
  describe a deploy it never made; only `publish_game_site` writes the registry
  dict this node reads.
"""

import logging
from collections.abc import Callable
from pathlib import Path

from langchain.messages import HumanMessage

from mabgames.graph.messages import message_text, tool_names_from_messages
from mabgames.graph.models import GameDeployRecord
from mabgames.graph.paths import build_html_path
from mabgames.graph.prompts import DEPLOYMENT_HUMAN_PROMPT
from mabgames.graph.state import GameStudioState
from mabgames.graph.tools.deploy_tools import DEPLOY_REQUIRE_TIER0, make_deploy_tools

logger = logging.getLogger(__name__)


def make_deploy_node(
    builds_dir: Path,
    agent_factory: Callable[[list], object],
    tools_factory: Callable[..., tuple[list, dict]] | None = None,
) -> Callable[[GameStudioState], dict]:
    """`tools_factory` is injected, not defaulted at import.

    It is the seam that keeps tests off the network: binding the real factory as
    a default argument would capture it before any test could replace it.
    """
    tools_factory = tools_factory or make_deploy_tools
    def deploy_node(state: GameStudioState) -> dict:
        game_title = state["game_title"]
        build = state["game_developments"][-1]
        design = next(
            record for record in state["game_designs"] if record.idea_id == build.idea_id
        )
        sub_title = design.brief.game_sub_title
        html_path = build_html_path(builds_dir, game_title, build.build_id)

        def _record(deployed: bool, summary: str, registry: dict | None = None) -> dict:
            registry = registry or {}
            return {
                "game_deployments": [
                    GameDeployRecord(
                        idea_id=build.idea_id,
                        build_id=build.build_id,
                        slug=registry.get("slug", ""),
                        site_url=registry.get("site_url", ""),
                        deployed=deployed,
                        summary=summary,
                    )
                ]
            }

        if DEPLOY_REQUIRE_TIER0 and not build.tier0_pass:
            return _record(False, "Deploy skipped: build failed Tier-0 validation.")

        if not html_path.exists():
            return _record(False, f"Deploy skipped: no build found at {html_path}.")

        tools, registry = tools_factory(
            builds_dir, game_title, build.build_id, sub_title=sub_title
        )
        agent = agent_factory(tools)
        instruction = DEPLOYMENT_HUMAN_PROMPT.format(
            GAME_TITLE=game_title, IDEA_ID=build.idea_id, game_sub_title=sub_title
        )

        try:
            agent_result = agent.invoke({"messages": [HumanMessage(content=instruction)]})
        except Exception:
            logger.exception("deploy invoke failed for build %s", build.build_id)
            agent_result = None

        messages = list(agent_result["messages"]) if agent_result else []
        summary = message_text(messages[-1]) if messages else "deploy agent produced no messages"

        if not registry.get("site_url"):
            summary = (
                f"{summary}\n\nNo live URL was recorded — the publish tool never succeeded.\n"
                f"Tools called: {tool_names_from_messages(messages) or ['none']}"
            )
            return _record(False, summary, registry)

        if registry.get("anonymous"):
            summary = f"{summary}\n\nWARNING: anonymous site — expires 24h after publish."

        return _record(True, summary, registry)

    return deploy_node
