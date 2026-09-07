"""HTTP routes for the studio.

Handlers are `def`, not `async def`, so FastAPI runs the blocking graph stream in
its threadpool and the event loop stays free.
"""

import uuid

from fastapi import APIRouter, HTTPException, Response, status

from mabgames.api import lifecycle
from mabgames.api.deps import GraphDep, SessionDep, SessionFactoryDep, TaskRunnerDep
from mabgames.api.schemas import (
    ApproveBuildIn,
    BuildOut,
    DeployOut,
    DesignOut,
    IdeaOut,
    RankedBuildOut,
    RunOut,
    RunSummary,
    SelectIdeaIn,
    StartRunIn,
    TitleOut,
)
from mabgames.domain import repository as repo
from mabgames.domain.models import Build, Deploy, Design, Run, RunStatus, Title

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


def _build_out(build: Build) -> BuildOut:
    return BuildOut(
        id=build.id,
        idea_id=build.idea_id,
        design_id=build.design_id,
        html_path=build.html_path,
        tier0_pass=build.tier0_pass,
        summary=build.summary,
        created_at=build.created_at,
    )


def _deploy_out(deploy: Deploy) -> DeployOut:
    return DeployOut(
        id=deploy.id,
        build_id=deploy.build_id,
        slug=deploy.slug,
        site_url=deploy.site_url,
        deployed=deploy.deployed,
        summary=deploy.summary,
        created_at=deploy.created_at,
    )


def _run_out(
    run: Run,
    interrupt: dict | None,
    designs: list[Design] | None = None,
    builds: list[Build] | None = None,
    deploys: list[Deploy] | None = None,
) -> RunOut:
    return RunOut(
        **_summary(run).model_dump(),
        awaiting=interrupt,
        designs=[_design_out(d) for d in designs or []],
        builds=[_build_out(b) for b in builds or []],
        deploys=[_deploy_out(d) for d in deploys or []],
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
    return _run_out(
        run,
        lifecycle.pending_interrupt(graph, run.id),
        builds=repo.builds_for_run(session, run),
        deploys=repo.deploys_for_run(session, run),
    )


def _require_run(session, run_id: uuid.UUID) -> Run:
    run = repo.get_run(session, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no run {run_id}")
    return run


@router.post("/runs/{run_id}/select", response_model=RunOut)
def select_idea(
    run_id: uuid.UUID, body: SelectIdeaIn, session: SessionDep, graph: GraphDep
) -> RunOut:
    """R2 — pick the idea that proceeds to DESIGN.

    Runs DESIGN and stops at the build gate, so this is seconds and cents. The
    expensive phase needs a separate, deliberate call.
    """
    run = _require_run(session, run_id)
    try:
        result = lifecycle.select_idea(session, graph, run, body.idea_id)
    except lifecycle.RunConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except lifecycle.UnknownIdea as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _run_out(result.run, result.interrupt, result.designs)


@router.post("/runs/{run_id}/build", response_model=RunOut)
def approve_build(
    run_id: uuid.UUID,
    body: ApproveBuildIn,
    session: SessionDep,
    graph: GraphDep,
    session_factory: SessionFactoryDep,
    run_task: TaskRunnerDep,
    response: Response,
) -> RunOut:
    """The build gate: approve the brief and DEVELOP -> DEPLOY runs.

    Approving returns `202` immediately and the build runs in the background —
    it takes minutes. Poll `GET /api/runs/{run_id}` for `developing`,
    `deploying`, `completed` or `failed`. Rejecting is instant and ends the run
    with no build; the idea simply stays `designed`.
    """
    run = _require_run(session, run_id)

    if not body.approved:
        try:
            result = lifecycle.approve_build(session, graph, run, False)
        except lifecycle.RunConflict as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        return _run_out(result.run, result.interrupt)

    if run.status is not RunStatus.AWAITING_BUILD_APPROVAL:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"run is {run.status.value}, not awaiting_build_approval",
        )

    run_task(lambda: lifecycle.approve_build_detached(session_factory, graph, run_id))
    response.status_code = status.HTTP_202_ACCEPTED
    session.refresh(run)
    return _run_out(run, lifecycle.pending_interrupt(graph, run.id))


@router.get("/builds/{build_id}", response_model=BuildOut)
def get_build(build_id: uuid.UUID, session: SessionDep) -> BuildOut:
    """One build: where it was written and whether Tier-0 passed."""
    build = session.get(Build, build_id)
    if build is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no build {build_id}")
    return _build_out(build)


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


def _require_title(session, title_id: uuid.UUID) -> Title:
    title = session.get(Title, title_id)
    if title is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no title {title_id}")
    return title


def _ranked_out(session, build: Build, score: float | None) -> RankedBuildOut:
    deploy = repo.live_deploy(session, build.id)
    return RankedBuildOut(
        **_build_out(build).model_dump(),
        score=score,
        ratings=repo.rating_count(session, build.id),
        site_url=deploy.site_url if deploy is not None else None,
    )


@router.get("/titles/{title_id}/leaderboard", response_model=list[RankedBuildOut])
def leaderboard(title_id: uuid.UUID, session: SessionDep) -> list[RankedBuildOut]:
    """Every build for a title, best-rated first (R7).

    Ranked on the mean human rating and nothing else (Q1). Unrated builds come
    last, newest first, with no score. Tier-0 is shown but never ranks.
    """
    _require_title(session, title_id)
    return [
        _ranked_out(session, build, score)
        for build, score in repo.leaderboard(session, title_id)
    ]


@router.get("/titles/{title_id}/candidate", response_model=RankedBuildOut)
def production_candidate(title_id: uuid.UUID, session: SessionDep) -> RankedBuildOut:
    """The one production candidate for a title (R7), or 404 if it has none yet.

    Computed live, not read from the `candidates` cache: that cache is for the
    start page that lists every title at once, and nothing populates it yet.
    """
    _require_title(session, title_id)
    build = repo.production_candidate(session, title_id)
    if build is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"title {title_id} has no candidate yet"
        )
    score = next(
        (s for b, s in repo.leaderboard(session, title_id) if b.id == build.id), None
    )
    return _ranked_out(session, build, score)
