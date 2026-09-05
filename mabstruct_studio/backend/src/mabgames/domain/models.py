"""The domain schema — AD1.

Seven tables from the schema sketch in REQUIREMENTS.md. Two properties are load
bearing and easy to undo by accident:

* **Status is not a column** (R3). It is derived from which stage rows exist for
  an idea — see `repository.idea_status`. Re-runs append rather than clobber, so
  an idea can have several builds, which R7 needs and a status enum could not hold.
* **Slug identity lives here** (AD5/Q4), never in a file inside the build output
  directory. The notebook wrote `herenow.json` beside the build; copying a folder
  copied its slug and three builds ended up overwriting one site.
"""

import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Column
from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(UTC)


class IdeaStatus(str, Enum):
    """R3's lifecycle. Derived, never stored."""

    IDEATED = "ideated"
    DESIGNED = "designed"
    DEVELOPED = "developed"
    DEPLOYED = "deployed"
    REJECTED = "rejected"
    FAILED = "failed"


class RefurbEntry(str, Enum):
    """R4/Q3 — where a refurbishment re-enters the pipeline."""

    DESIGN = "design"
    DEVELOP = "develop"


class Title(SQLModel, table=True):
    """R6's grouping key: every idea for "The Big Swallow" hangs off one row."""

    __tablename__ = "titles"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    title: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=_now)


class Idea(SQLModel, table=True):
    """R1 — every idea ideation generates, not just the chosen one.

    `Idea.id` is the notebook's `idea_id`: the UUID assigned after the LLM
    returns, which joins the records of every later stage.
    """

    __tablename__ = "ideas"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    title_id: uuid.UUID = Field(foreign_key="titles.id", index=True)
    sub_title: str
    genre: str
    style: str
    reason: str
    description: str
    features: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)
    rejected_at: datetime | None = None


class Design(SQLModel, table=True):
    """The whole GameDesignBrief, stored as one JSON document.

    It is authored wholesale by the design agent and never queried field by
    field, so seventeen columns would buy nothing.
    """

    __tablename__ = "designs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    idea_id: uuid.UUID = Field(foreign_key="ideas.id", index=True)
    brief: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)


class Build(SQLModel, table=True):
    """One DEVELOP run. Several per idea is normal (R4 refurbs, R7 comparisons)."""

    __tablename__ = "builds"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    idea_id: uuid.UUID = Field(foreign_key="ideas.id", index=True)
    design_id: uuid.UUID = Field(foreign_key="designs.id")
    html_path: str = ""
    # Tier-0 is recorded and gates deploys, but never ranks (R7/Q1).
    tier0_pass: bool = False
    summary: str = ""
    # R4's lineage: which build this refurbishes, and where it re-entered.
    refurb_of: uuid.UUID | None = Field(default=None, foreign_key="builds.id")
    refurb_entry: RefurbEntry | None = None
    created_at: datetime = Field(default_factory=_now)


class Deploy(SQLModel, table=True):
    """A here.now publish attempt. `deployed=False` records a Tier-0 gate skip."""

    __tablename__ = "deploys"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    build_id: uuid.UUID = Field(foreign_key="builds.id", index=True)
    slug: str = ""
    site_url: str = ""
    deployed: bool = False
    summary: str = ""
    created_at: datetime = Field(default_factory=_now)


class Feedback(SQLModel, table=True):
    """R4 — human feedback against one specific build.

    `rating` is R7's only ranking signal, and is optional: "the controls feel
    floaty" is a useful refurb request whether or not a number came with it.
    """

    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint("rating IS NULL OR rating BETWEEN 1 AND 5", name="ck_rating_1_5"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    build_id: uuid.UUID = Field(foreign_key="builds.id", index=True)
    rating: int | None = None
    comment: str = ""
    created_at: datetime = Field(default_factory=_now)


class Candidate(SQLModel, table=True):
    """R7's one production candidate per title.

    A cache, not a second source of truth: `repository.recompute_candidate`
    derives it and upserts. It exists so the AD5 start page can read the
    candidate for every title without running the ranking query per title.
    """

    __tablename__ = "candidates"

    title_id: uuid.UUID = Field(foreign_key="titles.id", primary_key=True)
    build_id: uuid.UUID = Field(foreign_key="builds.id")
    updated_at: datetime = Field(default_factory=_now)


class RunStatus(str, Enum):
    """Where a pipeline execution is. Distinct from `IdeaStatus`, which is derived."""

    RUNNING = "running"
    AWAITING_SELECTION = "awaiting_selection"
    AWAITING_BUILD_APPROVAL = "awaiting_build_approval"
    DEVELOPING = "developing"
    DEPLOYING = "deploying"
    COMPLETED = "completed"
    FAILED = "failed"


class Run(SQLModel, table=True):
    """One pipeline execution. **`Run.id` is the LangGraph `thread_id`** (R2).

    The domain DB owns the *list* of runs so "which runs are waiting on a human?"
    is an indexed query; the checkpointer still owns what any one run is doing
    right now. Without this table a run that has not finished IDEATION has
    produced no domain rows at all, so it would be invisible to the human who
    comes back days later from another process — and finding it would mean
    scanning checkpoint blobs, which is the thing AD1 rejected.

    `status` is a cache of the checkpointer's truth, refreshed on every drain —
    the same pattern as `candidates`.
    """

    __tablename__ = "runs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    title_id: uuid.UUID = Field(foreign_key="titles.id", index=True)
    status: RunStatus = Field(default=RunStatus.RUNNING, index=True)
    error: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
