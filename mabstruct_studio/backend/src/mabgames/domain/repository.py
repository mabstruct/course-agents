"""Queries the requirements actually name, plus the writers that feed them.

Every function takes an explicit `Session` so the graph, the API and the tests
can each supply their own — nothing here reaches for a global.

Ordering note: rows are ordered by `created_at`, which has microsecond
resolution. Two rows written inside the same microsecond have no defined order.
Accepted; this is a single-operator studio, not a write-heavy service.
"""

import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, col, select

from mabgames.domain.models import (
    Build,
    Candidate,
    Deploy,
    Design,
    Feedback,
    Idea,
    IdeaStatus,
    RefurbEntry,
    Run,
    RunStatus,
    Title,
)

# --------------------------------------------------------------------------- #
# Writers
# --------------------------------------------------------------------------- #


def get_or_create_title(session: Session, title: str) -> Title:
    """R6 — one row per game title, shared across runs and across time."""
    existing = session.exec(select(Title).where(Title.title == title)).first()
    if existing is not None:
        return existing
    row = Title(title=title)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _idea_id(idea: Mapping[str, Any]) -> uuid.UUID:
    """Honour the id the pipeline already assigned, else mint one.

    `ideation_node` tags every idea with a UUID *in graph state*, and each later
    stage joins on it — so the row and the state must carry the same id or the
    design would be recorded against an idea that does not exist. The LLM still
    never generates it; the node does. Accepts either spelling so the mapping can
    come straight from `GameIdea.model_dump()` or from an `Idea` row.
    """
    supplied = idea.get("idea_id") or idea.get("id")
    return uuid.UUID(str(supplied)) if supplied else uuid.uuid4()


def record_ideas(
    session: Session, title_id: uuid.UUID, ideas: Iterable[Mapping[str, Any]]
) -> list[Idea]:
    """R1 — persist *every* idea ideation produced, not just the chosen one."""
    rows = [
        Idea(
            id=_idea_id(idea),
            title_id=title_id,
            sub_title=idea["sub_title"],
            genre=idea["genre"],
            style=idea["style"],
            reason=idea["reason"],
            description=idea["description"],
            features=list(idea.get("features", [])),
        )
        for idea in ideas
    ]
    session.add_all(rows)
    session.commit()
    for row in rows:
        session.refresh(row)
    return rows


def reject_idea(session: Session, idea_id: uuid.UUID) -> Idea:
    """R3's terminal state. The human passed on this one."""
    idea = session.get(Idea, idea_id)
    if idea is None:
        raise LookupError(f"no idea {idea_id}")
    idea.rejected_at = datetime.now(UTC)
    session.add(idea)
    session.commit()
    session.refresh(idea)
    return idea


def record_design(session: Session, idea_id: uuid.UUID, brief: Mapping[str, Any]) -> Design:
    row = Design(idea_id=idea_id, brief=dict(brief))
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def record_build(
    session: Session,
    idea_id: uuid.UUID,
    design_id: uuid.UUID,
    *,
    html_path: str = "",
    tier0_pass: bool = False,
    summary: str = "",
    refurb_of: uuid.UUID | None = None,
    refurb_entry: RefurbEntry | None = None,
) -> Build:
    """One DEVELOP run. Appends — it never replaces an earlier build for the idea."""
    row = Build(
        idea_id=idea_id,
        design_id=design_id,
        html_path=html_path,
        tier0_pass=tier0_pass,
        summary=summary,
        refurb_of=refurb_of,
        refurb_entry=refurb_entry,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def record_deploy(
    session: Session,
    build_id: uuid.UUID,
    *,
    slug: str = "",
    site_url: str = "",
    deployed: bool = False,
    summary: str = "",
) -> Deploy:
    """AD5 — the slug is recorded here and nowhere else.

    A Tier-0 gate skip is a real row with `deployed=False`, matching the
    notebook's behaviour of recording a skipped deploy rather than raising.
    """
    row = Deploy(
        build_id=build_id,
        slug=slug,
        site_url=site_url,
        deployed=deployed,
        summary=summary,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def record_feedback(
    session: Session,
    build_id: uuid.UUID,
    *,
    rating: int | None = None,
    comment: str = "",
) -> Feedback:
    """R4 — feedback against one specific build, which stays playable (Q4)."""
    if rating is not None and not 1 <= rating <= 5:
        raise ValueError(f"rating must be 1-5, got {rating}")
    row = Feedback(build_id=build_id, rating=rating, comment=comment)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


# --------------------------------------------------------------------------- #
# R3 — status, derived from which stage rows exist
# --------------------------------------------------------------------------- #


def idea_status(session: Session, idea: Idea) -> IdeaStatus:
    """The newest stage an idea has reached.

    `rejected` wins over everything: it is an explicit human act, and an idea
    can be rejected after it was built. `failed` is only reported when no build
    for the idea ever went live — an earlier successful deploy outranks a later
    Tier-0 failure, because the idea did reach `deployed`.
    """
    if idea.rejected_at is not None:
        return IdeaStatus.REJECTED

    builds = session.exec(
        select(Build)
        .where(Build.idea_id == idea.id)
        .order_by(col(Build.created_at).desc())
    ).all()

    if builds:
        live = session.exec(
            select(Deploy)
            .where(col(Deploy.build_id).in_([b.id for b in builds]))
            .where(Deploy.deployed == True)  # noqa: E712 — SQL, not Python truthiness
        ).first()
        if live is not None:
            return IdeaStatus.DEPLOYED
        if not builds[0].tier0_pass:
            return IdeaStatus.FAILED
        return IdeaStatus.DEVELOPED

    design = session.exec(select(Design).where(Design.idea_id == idea.id)).first()
    if design is not None:
        return IdeaStatus.DESIGNED

    return IdeaStatus.IDEATED


def ideas_for_title(
    session: Session, title_id: uuid.UUID
) -> list[tuple[Idea, IdeaStatus]]:
    """R3 + R6 — what the UI lists for a title, newest first, with status."""
    ideas = session.exec(
        select(Idea)
        .where(Idea.title_id == title_id)
        .order_by(col(Idea.created_at).desc())
    ).all()
    return [(idea, idea_status(session, idea)) for idea in ideas]


# --------------------------------------------------------------------------- #
# R7 — ranking and the production candidate
# --------------------------------------------------------------------------- #


def leaderboard(
    session: Session, title_id: uuid.UUID
) -> list[tuple[Build, float | None]]:
    """Builds for a title, best-rated first; unrated builds last.

    Ranked on the human 1-5 rating and nothing else (R7/Q1). Several people may
    rate one build, so the score is the mean. Sparse and subjective is accepted:
    an unrated build simply has no rank.
    """
    rows = session.exec(
        select(Build, func.avg(Feedback.rating))
        .join(Idea, col(Idea.id) == col(Build.idea_id))
        .join(Feedback, col(Feedback.build_id) == col(Build.id), isouter=True)
        .where(Idea.title_id == title_id)
        .group_by(col(Build.id))
    ).all()

    scored = [(build, float(avg) if avg is not None else None) for build, avg in rows]
    scored.sort(
        key=lambda pair: (pair[1] is not None, pair[1] or 0.0, pair[0].created_at),
        reverse=True,
    )
    return scored


def production_candidate(session: Session, title_id: uuid.UUID) -> Build | None:
    """R7 — exactly one candidate per title, or None if the title has no builds.

    The highest-rated build wins. With no ratings at all the fallback is the
    newest deployed build that passed Tier-0, so a title that nobody has rated
    still has a candidate to link to.
    """
    ranked = leaderboard(session, title_id)
    rated = [build for build, score in ranked if score is not None]
    if rated:
        return rated[0]

    return session.exec(
        select(Build)
        .join(Idea, col(Idea.id) == col(Build.idea_id))
        .join(Deploy, col(Deploy.build_id) == col(Build.id))
        .where(Idea.title_id == title_id)
        .where(Build.tier0_pass == True)  # noqa: E712
        .where(Deploy.deployed == True)  # noqa: E712
        .order_by(col(Deploy.created_at).desc())
    ).first()


def recompute_candidate(session: Session, title_id: uuid.UUID) -> Candidate | None:
    """Refresh the cached candidate. Call after a deploy or a new rating."""
    build = production_candidate(session, title_id)
    row = session.get(Candidate, title_id)

    if build is None:
        if row is not None:
            session.delete(row)
            session.commit()
        return None

    if row is None:
        row = Candidate(title_id=title_id, build_id=build.id)
    else:
        row.build_id = build.id
        row.updated_at = datetime.now(UTC)

    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def build_lineage(session: Session, build: Build) -> Sequence[Build]:
    """R4 — a build and every build it refurbishes, newest first."""
    chain = [build]
    seen = {build.id}
    current = build
    while current.refurb_of is not None and current.refurb_of not in seen:
        parent = session.get(Build, current.refurb_of)
        if parent is None:
            break
        chain.append(parent)
        seen.add(parent.id)
        current = parent
    return chain


# --------------------------------------------------------------------------- #
# R2 — runs, so a pause can be found again days later
# --------------------------------------------------------------------------- #


def list_titles(session: Session) -> list[Title]:
    """Every title the studio has worked on, newest first."""
    return list(
        session.exec(select(Title).order_by(col(Title.created_at).desc())).all()
    )


def create_run(session: Session, title_id: uuid.UUID) -> Run:
    """Start a run. Its `id` becomes the LangGraph thread_id."""
    row = Run(title_id=title_id)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def get_run(session: Session, run_id: uuid.UUID) -> Run | None:
    return session.get(Run, run_id)


def list_runs(session: Session, status: RunStatus | None = None) -> list[Run]:
    """R2 — `status=AWAITING_SELECTION` answers "which runs are waiting on me?"."""
    statement = select(Run)
    if status is not None:
        statement = statement.where(Run.status == status)
    return list(
        session.exec(statement.order_by(col(Run.created_at).desc())).all()
    )


def set_run_status(
    session: Session, run: Run, status: RunStatus, error: str | None = None
) -> Run:
    run.status = status
    run.error = error
    run.updated_at = datetime.now(UTC)
    session.add(run)
    session.commit()
    session.refresh(run)
    return run
