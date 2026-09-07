"""Structured outputs for the phase agents — ported verbatim from the notebook.

`idea_id` stays a `str` here on purpose. These are pydantic `response_format`
schemas shown to the LLM, and they must port unchanged so the notebook can keep
spiking against them. The conversion to `uuid.UUID` happens once, at the API
boundary in `api/lifecycle.py`, and nowhere else.
"""

from pydantic import BaseModel, Field


class GameIdea(BaseModel):
    """a conceptual game idea"""

    idea_id: str = Field(default="", description="Unique id assigned after ideation (not from the LLM)")
    sub_title: str = Field(description="a sub title for the game that triggers attention or interest to the player")
    genre: str = Field(description="game genre")
    style: str = Field(description="game style")
    reason: str = Field(description="reason why this idea is interesting and why it should be made")
    description: str = Field(description="an abstract to communicate the main idea of the game")
    features: list[str] = Field(description="features of the game")


class GameIdeaList(BaseModel):
    """a list of game ideas"""

    ideas: list[GameIdea] = Field(description="list of game ideas")


class GameDesignBrief(BaseModel):
    """
    The brief for the game.
    """

    game_title: str = Field(description="The title of the game")
    game_sub_title: str = Field(description="The sub title of the game")
    game_description: str = Field(description="A short description of the game in 2 to 5 sentences.")
    game_genre: str = Field(description="The genre of the game")
    game_theme: str = Field(description="The theme of the game")
    game_mood: str = Field(description="The mood of the game")
    game_style: str = Field(description="The style of the game")
    game_goal: str = Field(description="The goal of the game for the player")
    game_objective: str = Field(description="The objective of the game for the player")
    game_rules: str = Field(description="The rules of the game")
    game_controls: str = Field(description="The controls of the game")
    game_instructions: str = Field(description="The instructions of the game")
    game_mechanics: str = Field(description="The mechanics of the game")
    game_sound: str = Field(description="The sound of the game")
    game_art: str = Field(description="Describe the distinctive creative art and style of the game")
    hints_for_the_team: str = Field(description="Hints and additional information for the production and design team")


class GameDesignRecord(BaseModel):
    """Design brief linked to one ideation idea."""

    idea_id: str = Field(description="Matches GameIdea.idea_id")
    brief: GameDesignBrief


class GameDevelopRecord(BaseModel):
    """Built HTML game linked to one design brief.

    `build_id` is new against the notebook, which keyed everything on `idea_id`
    because it assumed one build per idea. Q4/AD5 says the build owns its URL and
    its output directory, so the build needs its own identity — minted by
    `develop_node` before it writes anything, the same way `ideation_node` mints
    `idea_id`.
    """

    idea_id: str = Field(description="Matches GameIdea.idea_id")
    build_id: str = Field(description="Unique id assigned by develop_node before writing")
    html_path: str = Field(description="Path to the written index.html")
    tier0_pass: bool = Field(description="Whether static Tier-0 validation passed")
    summary: str = Field(description="Developer confirmation: MVP vs deferred, validation notes")
    # R4 — the build this one patches, if any. Copied from state by develop_node
    # so the persister can record lineage without reading graph state.
    refurb_of: str | None = Field(default=None, description="build_id being refurbished, if any")


class GameDeployRecord(BaseModel):
    """Live here.now site linked to one built game."""

    idea_id: str = Field(description="Matches GameIdea.idea_id")
    build_id: str = Field(description="Matches GameDevelopRecord.build_id — the build owns the URL")
    slug: str = Field(default="", description="here.now slug, recorded in the domain DB")
    site_url: str = Field(default="", description="Live URL for internal playtesting")
    deployed: bool = Field(description="Whether the game is live and verified")
    summary: str = Field(description="Deployment confirmation: URL, permanence, gate notes")
