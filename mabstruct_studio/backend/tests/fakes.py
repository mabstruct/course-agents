"""Stand-ins for the phase agents, so tests run the real graph without an LLM.

The seam is *agent* injection, not graph faking. Tests exercise the real
topology, the real interrupt, the real checkpointer and the real dispatch table
— only the two `create_agent` results are swapped. A hand-built fake graph would
test a graph nobody ships, and recorded chunks would skip the interrupt/resume
mechanics, which is where all the risk in this slice lives.
"""

from mabgames.graph.models import GameDesignBrief, GameIdea, GameIdeaList


class FakeAgent:
    """Stands in for `create_agent(...)`. Records prompts so tests can assert on them."""

    def __init__(self, structured_response):
        self.response = structured_response
        self.calls: list[str] = []

    def invoke(self, payload):
        self.calls.append(payload["messages"][0].content)
        return {"structured_response": self.response}


def fake_ideas(count: int = 5) -> GameIdeaList:
    """Ideas with NO idea_id — the node must mint them, exactly as the LLM leaves them."""
    return GameIdeaList(
        ideas=[
            GameIdea(
                sub_title=f"Idea {n}",
                genre="arcade",
                style="neon vector",
                reason=f"reason {n}",
                description=f"description {n}",
                features=[f"feature {n}a", f"feature {n}b"],
            )
            for n in range(count)
        ]
    )


def fake_brief(sub_title: str = "Idea 2") -> GameDesignBrief:
    return GameDesignBrief(
        game_title="The Big Swallow",
        game_sub_title=sub_title,
        game_description="Swallow the sky before it swallows you.",
        game_genre="arcade",
        game_theme="cosmic",
        game_mood="surreal",
        game_style="neon vector",
        game_goal="swallow everything",
        game_objective="survive the escalation",
        game_rules="one button",
        game_controls="space",
        game_instructions="press space",
        game_mechanics="peristalsis timing",
        game_sound="low hum",
        game_art="hand-inked",
        hints_for_the_team="keep the verb single",
    )
