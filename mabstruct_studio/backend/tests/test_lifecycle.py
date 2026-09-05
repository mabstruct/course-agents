"""The persistence seam: the API writes domain rows, the graph nodes do not."""

import uuid

import pytest

from mabgames.api import lifecycle
from mabgames.api.lifecycle import NO_PERSIST, PERSISTERS
from mabgames.domain import repository as repo
from mabgames.domain.models import IdeaStatus, RunStatus
from mabgames.graph.studio import DESIGN_NODE


def test_ideas_are_persisted_before_the_human_is_asked(session, graph):
    """R1 + R2 — the pause is only useful if the ideas already exist."""
    result = lifecycle.start_run(session, graph, "The Big Swallow")

    assert result.run.status is RunStatus.AWAITING_SELECTION
    assert result.interrupt["kind"] == "select_idea"

    title = repo.get_or_create_title(session, "The Big Swallow")
    stored = repo.ideas_for_title(session, title.id)
    assert len(stored) == 5
    assert all(status is IdeaStatus.IDEATED for _, status in stored)


def test_db_and_graph_state_share_one_uuid(session, graph):
    """The join every later stage depends on.

    `ideation_node` mints the id in graph state; the repository has to honour it
    rather than assigning its own, or the design would be recorded against an
    idea that does not exist.
    """
    result = lifecycle.start_run(session, graph, "The Big Swallow")

    in_state = {idea["idea_id"] for idea in result.interrupt["ideas"]}
    in_db = {str(idea.id) for idea, _ in lifecycle.ideas_for_run(session, result.run)}
    assert in_db == in_state


def test_design_row_joins_the_chosen_idea(session, graph):
    started = lifecycle.start_run(session, graph, "The Big Swallow")
    chosen = uuid.UUID(started.interrupt["ideas"][2]["idea_id"])

    resumed = lifecycle.select_idea(session, graph, started.run, chosen)

    # Design done, paused at the build gate — nothing expensive has run.
    assert resumed.run.status is RunStatus.AWAITING_BUILD_APPROVAL
    assert resumed.interrupt["kind"] == "approve_build"
    assert len(resumed.designs) == 1
    assert resumed.designs[0].idea_id == chosen
    assert resumed.designs[0].brief["game_sub_title"] == "Idea 2"

    statuses = {
        idea.id: status for idea, status in lifecycle.ideas_for_run(session, resumed.run)
    }
    assert statuses[chosen] is IdeaStatus.DESIGNED


def test_unchosen_ideas_are_not_rejected(session, graph):
    """R1/R3 — not choosing is not rejecting. They are R7's comparison set."""
    started = lifecycle.start_run(session, graph, "The Big Swallow")
    chosen = uuid.UUID(started.interrupt["ideas"][2]["idea_id"])
    resumed = lifecycle.select_idea(session, graph, started.run, chosen)

    statuses = [s for _, s in lifecycle.ideas_for_run(session, resumed.run)]
    assert statuses.count(IdeaStatus.IDEATED) == 4
    assert IdeaStatus.REJECTED not in statuses


def test_selecting_an_idea_the_run_never_offered_is_refused(session, graph):
    started = lifecycle.start_run(session, graph, "The Big Swallow")

    with pytest.raises(lifecycle.UnknownIdea):
        lifecycle.select_idea(session, graph, started.run, uuid.uuid4())

    # The paused thread is untouched and still selectable — the payoff for
    # validating here rather than letting the node raise mid-stream.
    assert repo.get_run(session, started.run.id).status is RunStatus.AWAITING_SELECTION
    assert lifecycle.pending_interrupt(graph, started.run.id) is not None


def test_selecting_twice_is_a_conflict(session, graph):
    started = lifecycle.start_run(session, graph, "The Big Swallow")
    chosen = uuid.UUID(started.interrupt["ideas"][0]["idea_id"])
    lifecycle.select_idea(session, graph, started.run, chosen)

    with pytest.raises(lifecycle.RunConflict):
        lifecycle.select_idea(session, graph, started.run, chosen)


def test_an_unmapped_node_does_not_break_a_run(session, graph):
    """A new graph node must not 500 every in-flight run."""
    started = lifecycle.start_run(session, graph, "The Big Swallow")
    result = lifecycle._consume(
        session, started.run, iter([{"develop_node": {"game_developments": []}}])
    )
    assert result.designs == []


def test_every_graph_node_is_accounted_for(graph):
    """Makes the silent skip above loud at test time.

    Adding `develop_node` without either a persister or an explicit NO_PERSIST
    entry fails here rather than quietly persisting nothing in production.
    """
    nodes = set(graph.get_graph().nodes) - {"__start__", "__end__"}
    assert nodes <= set(PERSISTERS) | NO_PERSIST


def test_runs_awaiting_a_human_are_queryable(session, graph):
    """R2 — "which runs are waiting on me?" without scanning checkpoints."""
    first = lifecycle.start_run(session, graph, "The Big Swallow")
    lifecycle.start_run(session, graph, "Another Title")

    awaiting = repo.list_runs(session, RunStatus.AWAITING_SELECTION)
    assert len(awaiting) == 2

    lifecycle.select_idea(
        session, graph, first.run, uuid.UUID(first.interrupt["ideas"][0]["idea_id"])
    )
    assert len(repo.list_runs(session, RunStatus.AWAITING_SELECTION)) == 1
    assert len(repo.list_runs(session, RunStatus.AWAITING_BUILD_APPROVAL)) == 1


def test_design_persister_is_wired_to_the_design_node():
    assert DESIGN_NODE in PERSISTERS


def test_a_pause_survives_a_restart(session, agents, checkpoint_path, file_graph, recwarn):
    """R2's actual requirement: resume from another process, days later.

    A fresh SqliteSaver over the same file and a freshly compiled graph is the
    honest approximation of a restart inside one pytest process. Also pins the
    serializer allowlist: without it langgraph warns that deserializing
    GameIdeaList from a checkpoint "will be blocked in a future version", and
    this reload is exactly that path.
    """
    from mabgames.graph.studio import build_studio_graph, make_checkpointer

    started = lifecycle.start_run(session, file_graph, "The Big Swallow")
    chosen = uuid.UUID(started.interrupt["ideas"][3]["idea_id"])
    file_graph.checkpointer.conn.close()
    del file_graph

    reopened = build_studio_graph(
        ideation_agent=agents.ideation,
        design_agent=agents.design,
        checkpointer=make_checkpointer(checkpoint_path),
    )

    # The pause is still there, and the ideas came back as real pydantic objects.
    assert lifecycle.pending_interrupt(reopened, started.run.id) is not None
    state = reopened.get_state(lifecycle.thread_config(started.run.id))
    assert state.values["game_ideation"].ideas[3].idea_id == str(chosen)

    run = repo.get_run(session, started.run.id)
    resumed = lifecycle.select_idea(session, reopened, run, chosen)
    assert resumed.designs[0].idea_id == chosen
    assert resumed.run.status is RunStatus.AWAITING_BUILD_APPROVAL

    unregistered = [w for w in recwarn if "unregistered type" in str(w.message)]
    assert not unregistered, [str(w.message) for w in unregistered]
    reopened.checkpointer.conn.close()
