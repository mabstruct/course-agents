"""DEVELOP + DEPLOY through the seam: builds and deploys become domain rows."""

import uuid
from pathlib import Path

from fakes import BROKEN_GAME_HTML

from mabgames.api import lifecycle
from mabgames.domain import repository as repo
from mabgames.domain.models import Build, IdeaStatus, RunStatus


def _to_the_gate(session, graph, index=0):
    started = lifecycle.start_run(session, graph, "The Big Swallow")
    chosen = uuid.UUID(started.interrupt["ideas"][index]["idea_id"])
    at_gate = lifecycle.select_idea(session, graph, started.run, chosen)
    return at_gate.run, chosen


def test_the_gate_offers_the_brief_before_anything_is_spent(session, graph, builds_dir):
    run, _ = _to_the_gate(session, graph)

    assert run.status is RunStatus.AWAITING_BUILD_APPROVAL
    payload = lifecycle.pending_interrupt(graph, run.id)
    assert payload["kind"] == "approve_build"
    assert payload["brief"]["game_sub_title"] == "Idea 2"
    assert not builds_dir.exists(), "no build directory before approval"


def test_rejecting_the_brief_ends_the_run_with_no_build(session, graph, builds_dir):
    run, _ = _to_the_gate(session, graph)

    result = lifecycle.approve_build(session, graph, run, False)

    assert result.run.status is RunStatus.COMPLETED
    assert result.builds == []
    assert session.exec(__import__("sqlmodel").select(Build)).all() == []
    assert not builds_dir.exists()
    # The idea keeps the status its stage rows imply — no new state needed.
    (idea_status,) = {s for _, s in lifecycle.ideas_for_run(session, result.run) if s is IdeaStatus.DESIGNED}
    assert idea_status is IdeaStatus.DESIGNED


def test_approving_writes_a_build_row_and_a_real_file(session, graph, builds_dir):
    run, chosen = _to_the_gate(session, graph)

    result = lifecycle.approve_build(session, graph, run, True)

    assert result.run.status is RunStatus.COMPLETED
    assert len(result.builds) == 1
    build = result.builds[0]

    # The row carries the id the node minted, and the file is where it says.
    assert build.idea_id == chosen
    assert build.tier0_pass is True
    assert Path(build.html_path).exists()
    assert str(build.id) in build.html_path, "the build owns its directory (AD5)"
    assert Path(build.html_path).read_text().count("<script") == 1


def test_the_deploy_row_carries_the_slug(session, graph):
    run, _ = _to_the_gate(session, graph)
    result = lifecycle.approve_build(session, graph, run, True)

    assert len(result.deploys) == 1
    deploy = result.deploys[0]
    assert deploy.deployed is True
    assert deploy.slug == "hazy-hazel-6pws"
    assert deploy.site_url == "https://hazy-hazel-6pws.here.now"
    assert deploy.build_id == result.builds[0].id

    statuses = dict(
        (idea.id, status) for idea, status in lifecycle.ideas_for_run(session, result.run)
    )
    assert statuses[result.builds[0].idea_id] is IdeaStatus.DEPLOYED


def test_no_herenow_json_is_written_beside_the_build(session, graph, builds_dir):
    """AD5 — slug identity lives in the DB, never in a file a copy could duplicate."""
    run, _ = _to_the_gate(session, graph)
    lifecycle.approve_build(session, graph, run, True)

    assert list(builds_dir.rglob("index.html")), "sanity: a build was written"
    assert not list(builds_dir.rglob("herenow.json"))


def test_the_registry_beats_the_agents_claim(session, graph, agents, monkeypatch):
    """An agent can describe a deploy it never made. Only the publish tool counts.

    The fake deploy agent always ends by saying it deployed to
    https://liar.example; here it is told not to call the publish tool.
    """
    agents.deploy.publish = False
    run, _ = _to_the_gate(session, graph)

    result = lifecycle.approve_build(session, graph, run, True)

    deploy = result.deploys[0]
    assert deploy.deployed is False
    assert deploy.slug == "" and deploy.site_url == ""
    assert "liar.example" not in deploy.site_url
    assert "No live URL was recorded" in deploy.summary


def test_a_tier0_failure_is_recorded_and_blocks_the_deploy(session, graph, agents, builds_dir):
    """The gate is deterministic — the deploy agent never even runs."""
    agents.develop.html = BROKEN_GAME_HTML
    run, _ = _to_the_gate(session, graph)

    result = lifecycle.approve_build(session, graph, run, True)

    build = result.builds[0]
    assert build.tier0_pass is False
    assert "Tier-0 issues" in build.summary

    deploy = result.deploys[0]
    assert deploy.deployed is False
    assert "failed Tier-0" in deploy.summary
    assert agents.deploy.calls == [], "the deploy agent is not consulted at all"


def test_the_build_joins_the_design_written_before_the_pause(session, graph):
    """`design_id` is not in the build's delta — it came from an earlier segment."""
    run, chosen = _to_the_gate(session, graph)
    result = lifecycle.approve_build(session, graph, run, True)

    design = repo.latest_design(session, chosen)
    assert design is not None
    assert result.builds[0].design_id == design.id


def test_the_develop_prompt_carries_the_whole_brief(session, graph, agents):
    run, _ = _to_the_gate(session, graph)
    lifecycle.approve_build(session, graph, run, True)

    prompt = agents.develop.calls[0]
    for expected in ("Idea 2", "swallow everything", "peristalsis timing", "keep the verb single"):
        assert expected in prompt


def test_every_graph_node_is_still_accounted_for(graph):
    from mabgames.api.lifecycle import NO_PERSIST, PERSISTERS

    nodes = set(graph.get_graph().nodes) - {"__start__", "__end__"}
    assert nodes <= set(PERSISTERS) | NO_PERSIST
