"""The HTTP contract.

Kept separate from `graph/models.py` on purpose: those are pydantic schemas shown
to an LLM and must port verbatim from the notebook, while these are what a
browser sees. They are free to drift.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from mabgames.domain.models import IdeaStatus, RefurbEntry, RunStatus


class TitleOut(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime


class IdeaOut(BaseModel):
    idea_id: uuid.UUID
    sub_title: str
    genre: str
    style: str
    reason: str
    description: str
    features: list[str]
    status: IdeaStatus | None = None


class SelectIdeaPrompt(BaseModel):
    """The pending decision, taken from the interrupt payload."""

    kind: Literal["select_idea"]
    game_title: str
    ideas: list[IdeaOut]


class ApproveBuildPrompt(BaseModel):
    """The build gate: read the brief, then decide whether to pay for the build."""

    kind: Literal["approve_build"]
    game_title: str
    idea_id: uuid.UUID
    brief: dict


class DesignOut(BaseModel):
    id: uuid.UUID
    idea_id: uuid.UUID
    brief: dict
    created_at: datetime


class RunSummary(BaseModel):
    run_id: uuid.UUID
    title_id: uuid.UUID
    status: RunStatus
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class BuildOut(BaseModel):
    id: uuid.UUID
    idea_id: uuid.UUID
    design_id: uuid.UUID
    html_path: str
    tier0_pass: bool
    summary: str
    # R4 lineage: the build this one patches, and where it re-entered.
    refurb_of: uuid.UUID | None = None
    refurb_entry: RefurbEntry | None = None
    created_at: datetime


class DeployOut(BaseModel):
    id: uuid.UUID
    build_id: uuid.UUID
    slug: str
    site_url: str
    deployed: bool
    summary: str
    created_at: datetime


class RankedBuildOut(BuildOut):
    """One leaderboard row (R7): a build, its mean rating, and where to play it."""

    score: float | None = None
    ratings: int = 0
    site_url: str | None = None


class RunOut(RunSummary):
    # Present exactly when the run is paused. Taken from the interrupt payload —
    # not a DB query — so it is authoritative for what *this run* offered.
    awaiting: SelectIdeaPrompt | ApproveBuildPrompt | None = Field(
        default=None, discriminator="kind"
    )
    designs: list[DesignOut] = Field(default_factory=list)
    builds: list[BuildOut] = Field(default_factory=list)
    deploys: list[DeployOut] = Field(default_factory=list)


class StartRunIn(BaseModel):
    game_title: str


class SelectIdeaIn(BaseModel):
    idea_id: uuid.UUID


class ApproveBuildIn(BaseModel):
    approved: bool = True


class FeedbackIn(BaseModel):
    """R4 — a rating, a comment, or both. The rating is R7's only ranking signal."""

    rating: int | None = Field(default=None, ge=1, le=5)
    comment: str = ""


class FeedbackOut(FeedbackIn):
    id: uuid.UUID
    build_id: uuid.UUID
    created_at: datetime
