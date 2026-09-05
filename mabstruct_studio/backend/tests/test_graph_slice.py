"""The graph on its own: chunk order, the pause, and the chosen-idea fix."""

from langgraph.types import Command

from mabgames.graph.state import initial_state
from mabgames.graph.studio import DESIGN_NODE, IDEATION_NODE, SELECT_IDEA_NODE

CONFIG = {"configurable": {"thread_id": "slice"}}


def _run_to_pause(graph):
    return list(
        graph.stream(initial_state("The Big Swallow"), CONFIG, stream_mode="updates")
    )


def test_ideation_delta_arrives_before_the_pause(graph):
    """The property R1 + R2 compose on. It should fail loudly if langgraph changes it.

    The API persists ideas by consuming this stream, so the ideation delta must
    reach it *before* the interrupt — otherwise the human would be asked to
    choose between ideas that were never stored.
    """
    chunks = _run_to_pause(graph)
    assert [next(iter(c)) for c in chunks] == [IDEATION_NODE, "__interrupt__"]


def test_pause_offers_every_idea(graph):
    _run_to_pause(graph)
    snapshot = graph.get_state(CONFIG)

    assert snapshot.next == (SELECT_IDEA_NODE,)
    payload = snapshot.interrupts[0].value
    assert payload["kind"] == "select_idea"
    assert payload["game_title"] == "The Big Swallow"
    assert len(payload["ideas"]) == 5
    assert all(idea["idea_id"] for idea in payload["ideas"])


def test_the_node_mints_distinct_ids_not_the_llm(graph, agents):
    """The fake agent returns ideas with empty idea_ids; the node assigns them."""
    assert all(idea.idea_id == "" for idea in agents.ideation.response.ideas)
    _run_to_pause(graph)
    ids = [i["idea_id"] for i in graph.get_state(CONFIG).interrupts[0].value["ideas"]]
    assert len(set(ids)) == 5


def test_design_keys_off_the_chosen_idea(graph, agents):
    """Deliberately picks a NON-zero idea.

    The notebook formatted its prompt from `ideas[0]` while keying the record to
    `ideas[CHOSEN_IDEA_INDEX]`. Both halves of this assertion would fail under
    that behaviour.
    """
    _run_to_pause(graph)
    chosen = graph.get_state(CONFIG).interrupts[0].value["ideas"][2]

    chunks = list(
        graph.stream(
            Command(resume={"idea_id": chosen["idea_id"]}), CONFIG, stream_mode="updates"
        )
    )

    # DESIGN then the build gate — the expensive phase waits for a second act.
    assert [next(iter(c)) for c in chunks] == [
        SELECT_IDEA_NODE,
        DESIGN_NODE,
        "__interrupt__",
    ]
    record = graph.get_state(CONFIG).values["game_designs"][0]
    assert record.idea_id == chosen["idea_id"]
    assert chosen["sub_title"] in agents.design.calls[0]


def test_resuming_with_an_unknown_idea_is_refused(graph):
    _run_to_pause(graph)
    try:
        list(graph.stream(Command(resume={"idea_id": "not-a-real-id"}), CONFIG))
    except ValueError as exc:
        assert "not in this run" in str(exc)
    else:
        raise AssertionError("the node should refuse an idea it never offered")
