"""R4 — feedback against a build, and a refurb that re-enters at DEVELOP."""

import uuid

from mabgames.api import lifecycle
from mabgames.domain import repository as repo
from mabgames.domain.models import Build, RefurbEntry, RunStatus
from fakes import publish_responses


def _deployed_build(client) -> tuple[dict, str]:
    """Drive one run through the fake pipeline; return (run body, build id)."""
    run = client.post("/api/runs", json={"game_title": "The Big Swallow"}).json()
    chosen = run["awaiting"]["ideas"][2]["idea_id"]
    client.post(f"/api/runs/{run['run_id']}/select", json={"idea_id": chosen})
    client.post(f"/api/runs/{run['run_id']}/build", json={"approved": True})
    done = client.get(f"/api/runs/{run['run_id']}").json()
    return done, done["builds"][0]["id"]


# --------------------------------------------------------------------------- #
# Feedback
# --------------------------------------------------------------------------- #


def test_feedback_is_recorded_against_one_build(client):
    _, build_id = _deployed_build(client)

    created = client.post(
        f"/api/builds/{build_id}/feedback", json={"rating": 4, "comment": "floaty"}
    )
    assert created.status_code == 201, created.text
    assert created.json()["build_id"] == build_id

    note_only = client.post(f"/api/builds/{build_id}/feedback", json={"comment": "more hum"})
    assert note_only.status_code == 201 and note_only.json()["rating"] is None

    listed = client.get(f"/api/builds/{build_id}/feedback").json()
    assert [f["comment"] for f in listed] == ["floaty", "more hum"], "oldest first"


def test_a_rating_out_of_range_is_rejected(client):
    _, build_id = _deployed_build(client)
    assert client.post(f"/api/builds/{build_id}/feedback", json={"rating": 6}).status_code == 422
    assert client.post(f"/api/builds/{build_id}/feedback", json={"rating": 0}).status_code == 422


def test_feedback_on_an_unknown_build_is_404(client):
    missing = uuid.uuid4()
    assert client.post(f"/api/builds/{missing}/feedback", json={"rating": 3}).status_code == 404
    assert client.get(f"/api/builds/{missing}/feedback").status_code == 404
    assert client.post(f"/api/builds/{missing}/refurb").status_code == 404


def test_a_rating_over_http_moves_the_leaderboard(client):
    """R4 feeds R7: the loop closes without touching the repository directly."""
    done, build_id = _deployed_build(client)
    client.post(f"/api/builds/{build_id}/feedback", json={"rating": 5})

    board = client.get(f"/api/titles/{done['title_id']}/leaderboard").json()
    assert board[0]["id"] == build_id and board[0]["score"] == 5.0


# --------------------------------------------------------------------------- #
# Refurb at DEVELOP
# --------------------------------------------------------------------------- #


def test_a_refurb_is_a_new_build_that_names_its_parent(client, session, agents, herenow):
    """Q3's first loop: same brief, new build, new URL, lineage recorded."""
    done, parent_id = _deployed_build(client)
    # The stubbed transport holds one publish sequence; the refurb needs its own.
    herenow.session.responses.extend(publish_responses())
    client.post(f"/api/builds/{parent_id}/feedback", json={"rating": 2, "comment": "the controls feel floaty"})
    client.post(f"/api/builds/{parent_id}/feedback", json={"comment": "needs more hum"})

    accepted = client.post(f"/api/builds/{parent_id}/refurb")
    assert accepted.status_code == 202, accepted.text
    refurb_run = accepted.json()
    assert refurb_run["run_id"] != done["run_id"]
    assert refurb_run["title_id"] == done["title_id"]

    # The inline runner has already finished it.
    finished = client.get(f"/api/runs/{refurb_run['run_id']}").json()
    assert finished["status"] == "completed"
    builds = {b["id"]: b for b in finished["builds"]}
    assert len(builds) == 2, "the refurb appends; it never replaces the parent"
    (child,) = [b for b in builds.values() if b["id"] != parent_id]
    assert child["refurb_of"] == parent_id
    assert child["refurb_entry"] == "develop"
    assert child["idea_id"] == builds[parent_id]["idea_id"]
    assert child["design_id"] == builds[parent_id]["design_id"], "DEVELOP re-entry keeps the design"
    assert child["tier0_pass"] is True

    # The develop agent was told what players said, and which build it patches.
    prompt = agents.develop.calls[-1]
    assert "REFURBISHMENT" in prompt and parent_id in prompt
    assert "[rated 2/5] the controls feel floaty" in prompt
    assert "needs more hum" in prompt
    assert "Sub-title: Idea 2" in prompt, "the same brief is the specification"

    # No idea choice and no build gate on the way: the graph entered at DEVELOP.
    assert agents.ideation.calls == [] or len(agents.ideation.calls) == 1
    assert len(agents.design.calls) == 1

    lineage = client.get(f"/api/builds/{child['id']}/lineage").json()
    assert [b["id"] for b in lineage] == [child["id"], parent_id]

    # Both builds are live at their own site — nothing overwrote the parent (Q4).
    deploys = {d["build_id"]: d for d in finished["deploys"]}
    assert deploys[child["id"]]["deployed"] is True
    assert deploys[parent_id]["deployed"] is True


def test_a_build_with_no_feedback_cannot_be_refurbished(client, session):
    _, build_id = _deployed_build(client)

    response = client.post(f"/api/builds/{build_id}/refurb")
    assert response.status_code == 409
    assert len(repo.list_runs(session)) == 1, "no run was reserved"


def test_refurb_lifecycle_records_lineage_without_the_http_layer(session, graph):
    """The seam itself: `refurb_of` on the develop record becomes the domain row."""
    started = lifecycle.start_run(session, graph, "The Big Swallow")
    chosen = uuid.UUID(started.interrupt["ideas"][0]["idea_id"])
    at_gate = lifecycle.select_idea(session, graph, started.run, chosen)
    built = lifecycle.approve_build(session, graph, at_gate.run, True)
    parent = built.builds[0]
    repo.record_feedback(session, parent.id, comment="too fast")

    run = lifecycle.create_refurb_run(session, parent)
    assert run.status is RunStatus.DEVELOPING
    result = lifecycle.refurb_build(session, graph, run, parent)

    assert result.run.status is RunStatus.COMPLETED
    child = result.builds[0]
    assert child.refurb_of == parent.id
    assert child.refurb_entry is RefurbEntry.DEVELOP
    assert [b.id for b in repo.build_lineage(session, session.get(Build, child.id))] == [
        child.id,
        parent.id,
    ]
