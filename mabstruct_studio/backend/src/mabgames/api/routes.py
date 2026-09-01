"""HTTP routes for the studio.

Handlers are `def`, not `async def`, so FastAPI runs the blocking graph stream in
its threadpool and the event loop stays free.
"""

import uuid

from fastapi import APIRouter, HTTPException, status

from mabgames.api import lifecycle
from mabgames.api.deps import GraphDep, SessionDep
from mabgames.api.schemas import (
    DesignOut,
    IdeaOut,
    RunOut,
    RunSummary,
    SelectIdeaIn,
    StartRunIn,
    TitleOut,
)
from mabgames.domain import repository as repo
from mabgames.domain.models import Design, Run, RunStatus

router = APIRouter()


def _design_out(design: Design) -> DesignOut:
    return DesignOut(
        id=design.id,
        idea_id=design.idea_id,
        brief=design.brief,
        created_at=design.created_at,
    )


def _summary(run: Run) -> RunSummary:
    return RunSummary(
        run_id=run.id,
        title_id=run.title_id,
        status=run.status,
        error=run.error,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _run_out(run: Run, interrupt: dict | None, designs: list[Design]) -> RunOut:
    return RunOut(
        **_summary(run).model_dump(),
        awaiting=interrupt,
        designs=[_design_out(d) for d in designs],
    )


@router.post("/runs", response_model=RunOut, status_code=status.HTTP_201_CREATED)
def start_run(body: StartRunIn, session: SessionDep, graph: GraphDep) -> RunOut:
    """Ideate for a title and pause for a human to choose (R1, R2, R6).

    Blocks for the length of IDEATION. Background jobs and streamed progress
    arrive with DEVELOP, which is the phase that actually needs them.
    """
    result = lifecycle.start_run(session, graph, body.game_title)
    return _run_out(result.run, result.interrupt, result.designs)


@router.get("/runs", response_model=list[RunSummary])
def list_runs(session: SessionDep, run_status: RunStatus | None = None) -> list[RunSummary]:
    """All runs. `?run_status=awaiting_selection` is "what is waiting on me?"."""
    return [_summary(run) for run in repo.list_runs(session, run_status)]


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: uuid.UUID, session: SessionDep, graph: GraphDep) -> RunOut:
    """One run: its domain row, plus whatever the thread is waiting on right now."""
    run = repo.get_run(session, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no run {run_id}")
    return _run_out(run, lifecycle.pending_interrupt(graph, run.id), [])


@router.post("/runs/{run_id}/select", response_model=RunOut)
def select_idea(
    run_id: uuid.UUID, body: SelectIdeaIn, session: SessionDep, graph: GraphDep
) -> RunOut:
    """R2 — pick the idea that proceeds to DESIGN, and resume the run."""
    run = repo.get_run(session, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no run {run_id}")
    try:
        result = lifecycle.resume_run(session, graph, run, body.idea_id)
    except lifecycle.RunConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except lifecycle.UnknownIdea as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _run_out(result.run, result.interrupt, result.designs)


@router.get("/titles", response_model=list[TitleOut])
def list_titles(session: SessionDep) -> list[TitleOut]:
    """Every title the studio has worked on (R6)."""
    return [
        TitleOut(id=t.id, title=t.title, created_at=t.created_at)
        for t in repo.list_titles(session)
    ]


@router.get("/titles/{title_id}/ideas", response_model=list[IdeaOut])
def list_ideas(title_id: uuid.UUID, session: SessionDep) -> list[IdeaOut]:
    """Ideas for a title with their derived status (R3 + R6)."""
    return [
        IdeaOut(
            idea_id=idea.id,
            sub_title=idea.sub_title,
            genre=idea.genre,
            style=idea.style,
            reason=idea.reason,
            description=idea.description,
            features=idea.features,
            status=idea_status,
        )
        for idea, idea_status in repo.ideas_for_title(session, title_id)
    ]
