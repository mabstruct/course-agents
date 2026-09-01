"""The HTTP contract.

Kept separate from `graph/models.py` on purpose: those are pydantic schemas shown
to an LLM and must port verbatim from the notebook, while these are what a
browser sees. They are free to drift.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from mabgames.domain.models import IdeaStatus, RunStatus


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


class RunOut(RunSummary):
    # Present exactly when status is awaiting_selection. This — not a DB query —
    # is the authoritative list of what *this run* offered.
    awaiting: SelectIdeaPrompt | None = None
    designs: list[DesignOut] = Field(default_factory=list)


class StartRunIn(BaseModel):
    game_title: str


class SelectIdeaIn(BaseModel):
    idea_id: uuid.UUID
