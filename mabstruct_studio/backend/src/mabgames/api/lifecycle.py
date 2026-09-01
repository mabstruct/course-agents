"""The run lifecycle — where domain persistence happens.

**This module is the architectural decision.** The graph nodes are pure state
transformers that know nothing about the database; this layer consumes their
update stream and writes the domain rows. That keeps `graph/` portable back to
the spike notebook, keeps every domain write in one place, and costs almost
nothing, because the API has to consume that stream anyway.

Two properties of `stream_mode="updates"` make it work, both verified against
langgraph 1.2.4:

* chunks arrive as plain `{node_name: delta}` dicts, so dispatch is a dict lookup;
* **the ideation delta arrives before `__interrupt__`**, so the ideas are on disk
  before the human is asked to choose between them. That is R2, and it falls out
  of the stream ordering rather than having to be arranged.

This is also the only module that converts between the graph's `str` ids and the
domain's `uuid.UUID`.
"""

import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from langgraph.types import Command
from sqlmodel import Session

from mabgames.domain import repository as repo
from mabgames.domain.models import Design, Idea, Run, RunStatus
from mabgames.graph.studio import DESIGN_NODE, IDEATION_NODE, SELECT_IDEA_NODE

INTERRUPT_KEY = "__interrupt__"


class RunConflict(Exception):
    """The run is not in a state where the requested action makes sense."""


class UnknownIdea(Exception):
    """The chosen idea is not one this run offered."""


@dataclass
class RunResult:
    """What a start or resume produced. Routes turn this into a response model."""

    run: Run
    interrupt: dict[str, Any] | None = None
    designs: list[Design] = field(default_factory=list)


def thread_config(run_id: uuid.UUID) -> dict[str, Any]:
    """`Run.id` *is* the thread_id — no second column to keep in sync."""
    return {"configurable": {"thread_id": str(run_id)}}


def pending_interrupt(graph, run_id: uuid.UUID) -> dict[str, Any] | None:
    """What this run is waiting on right now, straight from the checkpointer.

    The domain DB answers what exists across runs; the checkpointer answers what
    one run is doing this second. Nothing is copied from state into the DB purely
    to make it queryable — that is the AD1 line.
    """
    snapshot = graph.get_state(thread_config(run_id))
    if not snapshot.interrupts:
        return None
    return snapshot.interrupts[0].value


# --------------------------------------------------------------------------- #
# node name -> repository call
# --------------------------------------------------------------------------- #


def _persist_ideation(session: Session, run: Run, delta: dict) -> list[Design]:
    ideation = delta["game_ideation"]
    repo.record_ideas(
        session, run.title_id, [idea.model_dump() for idea in ideation.ideas]
    )
    return []


def _persist_design(session: Session, run: Run, delta: dict) -> list[Design]:
    return [
        repo.record_design(
            session, uuid.UUID(record.idea_id), record.brief.model_dump()
        )
        for record in delta["game_designs"]
    ]


PERSISTERS = {IDEATION_NODE: _persist_ideation, DESIGN_NODE: _persist_design}

# Nodes that deliberately write no domain row. The human's choice is expressed by
# which idea gets a design — it needs no record of its own.
NO_PERSIST = {SELECT_IDEA_NODE}


def _consume(session: Session, run: Run, stream: Iterable[dict]) -> RunResult:
    """Drain the graph's update stream, persisting as each node reports.

    **One commit per node**, inherited from the repository writers. Do not
    retrofit a transaction over the whole loop: per-node commits make persistence
    granularity match *checkpoint* granularity. If the process dies between
    ideation and design, the ideas are on disk and the checkpoint holds the
    pause — exactly the state R2 wants to come back to. A run-wide transaction
    would roll those ideas back and leave a checkpoint pointing at rows that no
    longer exist.

    A chunk for an unmapped node is ignored, so a new node cannot 500 every
    in-flight run. That silence is made loud at test time instead, by
    `test_every_graph_node_is_accounted_for`.
    """
    result = RunResult(run=run)
    for chunk in stream:
        for node_name, delta in chunk.items():
            if node_name == INTERRUPT_KEY:
                result.interrupt = delta[0].value
                continue
            persist = PERSISTERS.get(node_name)
            if persist is None:
                continue
            result.designs.extend(persist(session, run, delta))
    return result


def _finish(session: Session, result: RunResult) -> RunResult:
    status = RunStatus.AWAITING_SELECTION if result.interrupt else RunStatus.COMPLETED
    repo.set_run_status(session, result.run, status)
    return result


def _drive(session: Session, graph, run: Run, stream: Iterator[dict]) -> RunResult:
    try:
        return _finish(session, _consume(session, run, stream))
    except Exception as exc:
        # Rows already committed stay committed and the checkpoint stays
        # resumable; only the run is marked failed.
        repo.set_run_status(session, run, RunStatus.FAILED, error=repr(exc))
        raise


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def start_run(session: Session, graph, game_title: str) -> RunResult:
    """R1 + R6 — ideate for a title, persist every idea, pause for the human."""
    from mabgames.graph.state import initial_state

    title = repo.get_or_create_title(session, game_title)
    run = repo.create_run(session, title.id)
    stream = graph.stream(
        initial_state(game_title), thread_config(run.id), stream_mode="updates"
    )
    return _drive(session, graph, run, stream)


def resume_run(session: Session, graph, run: Run, idea_id: uuid.UUID) -> RunResult:
    """R2 — the human's choice, days later and in another process.

    The choice is validated *before* `Command` is constructed. Raising inside the
    node would leave the run half-advanced behind an opaque 500; validating here
    leaves the paused thread pristine and immediately re-selectable.
    """
    if run.status is not RunStatus.AWAITING_SELECTION:
        raise RunConflict(f"run is {run.status.value}, not awaiting a selection")

    payload = pending_interrupt(graph, run.id)
    if payload is None:
        raise RunConflict("run is recorded as awaiting a selection but the thread is not paused")

    offered = {idea["idea_id"] for idea in payload.get("ideas", [])}
    if str(idea_id) not in offered:
        raise UnknownIdea(f"idea {idea_id} was not offered by this run")

    repo.set_run_status(session, run, RunStatus.RUNNING)
    stream = graph.stream(
        Command(resume={"idea_id": str(idea_id)}),
        thread_config(run.id),
        stream_mode="updates",
    )
    return _drive(session, graph, run, stream)


def ideas_for_run(session: Session, run: Run) -> list[tuple[Idea, Any]]:
    """Every idea stored for this run's title, with derived status (R3 + R6)."""
    return repo.ideas_for_title(session, run.title_id)
