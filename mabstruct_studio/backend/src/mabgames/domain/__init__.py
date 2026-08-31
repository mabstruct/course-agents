"""AD1's domain layer: the durable asset of this project.

A sibling of `graph/`, never nested inside it — the schema is meant to outlive
the pipeline that fills it.
"""

from mabgames.domain.db import create_db_and_tables, get_engine, get_session
from mabgames.domain.models import (
    Build,
    Candidate,
    Deploy,
    Design,
    Feedback,
    Idea,
    IdeaStatus,
    RefurbEntry,
    Title,
)

__all__ = [
    "Build",
    "Candidate",
    "Deploy",
    "Design",
    "Feedback",
    "Idea",
    "IdeaStatus",
    "RefurbEntry",
    "Title",
    "create_db_and_tables",
    "get_engine",
    "get_session",
]
